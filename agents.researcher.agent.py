"""
VeriSynthOS Researcher Agent
Purpose: Gather, summarize, and annotate unstructured information from web search, 
scholarly sources, and news. Produce concise literature reviews with credibility scoring.
"""

import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from enum import Enum

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import requests
from bs4 import BeautifulSoup
import time

from agents.core.llm_router import llm_call
from agents.core.maker import first_to_ahead_by_k, strict_json_parser

log = logging.getLogger("researcher")
log.setLevel(logging.INFO)

app = FastAPI(title="VeriSynthOS Researcher Agent")

# ------------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------------
credentials = None
project_id = None
custom_search_service = None

# Configuration
import os
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")  # Custom Search Engine ID
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# Rate limiting
RATE_LIMIT_DELAY = 1.0  # seconds between requests per domain
last_request_times: Dict[str, float] = {}

# ------------------------------------------------------------------
# PYDANTIC MODELS
# ------------------------------------------------------------------
class SourceType(str, Enum):
    WEB = "web"
    SCHOLARLY = "scholarly"
    NEWS = "news"
    ARXIV = "arxiv"
    PUBMED = "pubmed"

class ResearchRequest(BaseModel):
    query: str
    max_results: int = Field(default=30, le=100)
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    source_types: List[SourceType] = Field(default=[SourceType.WEB, SourceType.SCHOLARLY])
    domain_allowlist: Optional[List[str]] = None
    domain_blocklist: Optional[List[str]] = None
    language: str = "en"

class Source(BaseModel):
    id: str
    title: str
    url: str
    date: Optional[str]
    snippet: str
    summary: str
    type: SourceType
    credibility_score: float = Field(ge=0.0, le=1.0)
    suggested_embedding_text: str
    authors: Optional[List[str]] = None
    citations: Optional[int] = None

class ResearchResponse(BaseModel):
    sources: List[Source]
    synthesis: str
    top_sources_for_rag: List[str]  # List of source IDs
    query: str
    total_found: int

# ------------------------------------------------------------------
# STARTUP
# ------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global credentials, project_id, custom_search_service
    
    try:
        if GOOGLE_API_KEY and GOOGLE_CSE_ID:
            custom_search_service = build("customsearch", "v1", 
                                         developerKey=GOOGLE_API_KEY,
                                         cache_discovery=False)
            log.info("✅ Google Custom Search initialized")
        else:
            log.warning("⚠️  Google Custom Search not configured")
        
        log.info("✅ VeriSynthOS Researcher Agent started")
        
    except Exception as e:
        log.warning(f"⚠️  Startup issue: {e}")

# ------------------------------------------------------------------
# RATE LIMITING & POLITENESS
# ------------------------------------------------------------------
def respect_rate_limit(domain: str):
    """Enforce per-domain rate limiting"""
    if domain in last_request_times:
        elapsed = time.time() - last_request_times[domain]
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
    last_request_times[domain] = time.time()

# ------------------------------------------------------------------
# CREDIBILITY SCORING
# ------------------------------------------------------------------
def calculate_credibility(source: Dict) -> float:
    """
    Calculate credibility score based on multiple factors:
    - Domain authority (gov, edu, peer-reviewed journals)
    - Recency
    - Citation count (for scholarly)
    - Presence of author information
    """
    score = 0.5  # baseline
    
    url = source.get("url", "").lower()
    
    # Domain authority
    if ".gov" in url:
        score += 0.3
    elif ".edu" in url:
        score += 0.25
    elif any(journal in url for journal in ["nature.com", "science.org", "ieee.org", "acm.org"]):
        score += 0.3
    elif any(news in url for news in ["reuters.com", "apnews.com", "bbc.com"]):
        score += 0.2
    
    # Recency (within 2 years)
    if source.get("date"):
        try:
            date = datetime.fromisoformat(source["date"].replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - date).days
            if age_days < 730:  # < 2 years
                score += 0.1
        except:
            pass
    
    # Citations (for scholarly)
    citations = source.get("citations", 0)
    if citations > 100:
        score += 0.1
    elif citations > 10:
        score += 0.05
    
    # Author information
    if source.get("authors"):
        score += 0.05
    
    return min(1.0, score)

# ------------------------------------------------------------------
# WEB SEARCH
# ------------------------------------------------------------------
def search_web(query: str, max_results: int = 30, date_from: str = None, date_to: str = None) -> List[Dict]:
    """Search using Google Custom Search API"""
    if not custom_search_service or not GOOGLE_CSE_ID:
        log.warning("Custom Search not configured")
        return []
    
    results = []
    
    try:
        # Build date restriction if provided
        date_restrict = None
        if date_from and date_to:
            date_restrict = f"date:r:{date_from}:{date_to}"
        
        # Paginate through results (max 10 per request)
        for start_index in range(1, min(max_results, 100), 10):
            respect_rate_limit("googleapis.com")
            
            response = custom_search_service.cse().list(
                q=query,
                cx=GOOGLE_CSE_ID,
                num=min(10, max_results - len(results)),
                start=start_index,
                dateRestrict=date_restrict
            ).execute()
            
            for item in response.get("items", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("link"),
                    "snippet": item.get("snippet", ""),
                    "date": item.get("pagemap", {}).get("metatags", [{}])[0].get("article:published_time"),
                    "type": "web"
                })
            
            if len(results) >= max_results:
                break
        
        log.info(f"Found {len(results)} web results for: {query}")
        return results
        
    except HttpError as e:
        log.error(f"Custom Search API error: {e}")
        return []

# ------------------------------------------------------------------
# SCHOLARLY SEARCH (Semantic Scholar)
# ------------------------------------------------------------------
def search_scholarly(query: str, max_results: int = 20) -> List[Dict]:
    """Search scholarly articles via Semantic Scholar API"""
    results = []
    
    try:
        headers = {}
        if SEMANTIC_SCHOLAR_API_KEY:
            headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
        
        respect_rate_limit("semanticscholar.org")
        
        response = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "limit": max_results,
                "fields": "title,authors,year,abstract,citationCount,url,publicationDate"
            },
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            for paper in data.get("data", []):
                results.append({
                    "title": paper.get("title"),
                    "url": paper.get("url") or f"https://www.semanticscholar.org/paper/{paper.get('paperId')}",
                    "snippet": (paper.get("abstract") or "")[:300],
                    "date": paper.get("publicationDate"),
                    "type": "scholarly",
                    "authors": [a.get("name") for a in paper.get("authors", [])],
                    "citations": paper.get("citationCount", 0)
                })
        
        log.info(f"Found {len(results)} scholarly results for: {query}")
        return results
        
    except Exception as e:
        log.error(f"Semantic Scholar search failed: {e}")
        return []

# ------------------------------------------------------------------
# NEWS SEARCH
# ------------------------------------------------------------------
def search_news(query: str, max_results: int = 20, date_from: str = None, date_to: str = None) -> List[Dict]:
    """Search news articles via NewsAPI"""
    if not NEWS_API_KEY:
        log.warning("NewsAPI not configured")
        return []
    
    results = []
    
    try:
        respect_rate_limit("newsapi.org")
        
        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "apiKey": NEWS_API_KEY,
                "pageSize": max_results,
                "from": date_from,
                "to": date_to,
                "language": "en",
                "sortBy": "relevancy"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            for article in data.get("articles", []):
                results.append({
                    "title": article.get("title"),
                    "url": article.get("url"),
                    "snippet": article.get("description", ""),
                    "date": article.get("publishedAt"),
                    "type": "news",
                    "authors": [article.get("author")] if article.get("author") else []
                })
        
        log.info(f"Found {len(results)} news results for: {query}")
        return results
        
    except Exception as e:
        log.error(f"NewsAPI search failed: {e}")
        return []

# ------------------------------------------------------------------
# SUMMARIZATION WITH MAKER VOTING
# ------------------------------------------------------------------
def summarize_source(title: str, snippet: str, url: str) -> str:
    """Generate a concise summary using MAKER voting"""
    
    def sampler(task_input: dict) -> str:
        prompt = f"""Summarize this source in 2-4 sentences. Focus on key findings and relevance.

Title: {task_input['title']}
Content: {task_input['snippet']}
URL: {task_input['url']}

Return ONLY a JSON object with key 'summary' containing the summary text."""
        
        return llm_call(
            prompt=prompt,
            system_prompt="You are a precise research summarizer. Return only valid JSON.",
            max_tokens=200,
            temperature=0.3
        )
    
    class SummaryOutput(BaseModel):
        summary: str
    
    try:
        result = first_to_ahead_by_k(
            task_input={"title": title, "snippet": snippet, "url": url},
            sampler=sampler,
            parser=lambda raw: strict_json_parser(raw, SummaryOutput),
            k=3,
            max_tokens=200
        )
        return result.summary
    except Exception as e:
        log.error(f"Summarization failed: {e}")
        return snippet[:200] + "..."

# ------------------------------------------------------------------
# SYNTHESIS GENERATION
# ------------------------------------------------------------------
def generate_synthesis(sources: List[Source], query: str) -> str:
    """Generate overall synthesis from all sources"""
    
    # Prepare source summaries
    source_text = "\n\n".join([
        f"[{i+1}] {s.title}\n{s.summary}\nCredibility: {s.credibility_score:.2f}"
        for i, s in enumerate(sources[:15])  # Top 15 sources
    ])
    
    prompt = f"""Generate a comprehensive 3-6 paragraph synthesis of research findings on: "{query}"

Sources:
{source_text}

Requirements:
- Identify key themes and findings
- Note areas of consensus and contradiction
- Highlight most credible sources
- Provide actionable insights
- Use bullet points for key findings

Return a well-structured synthesis."""
    
    try:
        synthesis = llm_call(
            prompt=prompt,
            system_prompt="You are an expert research analyst. Provide clear, evidence-based synthesis.",
            max_tokens=1500,
            temperature=0.5
        )
        return synthesis
    except Exception as e:
        log.error(f"Synthesis generation failed: {e}")
        return "Synthesis generation failed. Please review individual sources."

# ------------------------------------------------------------------
# MAIN RESEARCH ENDPOINT
# ------------------------------------------------------------------
@app.post("/research", response_model=ResearchResponse)
async def research(req: ResearchRequest) -> ResearchResponse:
    """
    Main research endpoint - gathers and synthesizes information from multiple sources
    """
    log.info(f"Research request: {req.query}")
    
    all_results = []
    
    # Gather from requested source types
    if SourceType.WEB in req.source_types:
        all_results.extend(search_web(req.query, req.max_results // 2, req.date_from, req.date_to))
    
    if SourceType.SCHOLARLY in req.source_types:
        all_results.extend(search_scholarly(req.query, req.max_results // 3))
    
    if SourceType.NEWS in req.source_types:
        all_results.extend(search_news(req.query, req.max_results // 3, req.date_from, req.date_to))
    
    # Apply domain filters
    if req.domain_allowlist:
        all_results = [r for r in all_results if any(domain in r["url"] for domain in req.domain_allowlist)]
    
    if req.domain_blocklist:
        all_results = [r for r in all_results if not any(domain in r["url"] for domain in req.domain_blocklist)]
    
    # Deduplicate by URL
    seen_urls = set()
    unique_results = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique_results.append(r)
    
    # Process each source
    sources = []
    for result in unique_results[:req.max_results]:
        # Calculate credibility
        credibility = calculate_credibility(result)
        
        # Generate summary
        summary = summarize_source(
            result.get("title", ""),
            result.get("snippet", ""),
            result.get("url", "")
        )
        
        # Create embedding-ready text
        embedding_text = f"{result.get('title', '')}. {summary}"
        
        source = Source(
            id=hashlib.md5(result["url"].encode()).hexdigest()[:12],
            title=result.get("title", "Untitled"),
            url=result["url"],
            date=result.get("date"),
            snippet=result.get("snippet", ""),
            summary=summary,
            type=result["type"],
            credibility_score=credibility,
            suggested_embedding_text=embedding_text,
            authors=result.get("authors"),
            citations=result.get("citations")
        )
        sources.append(source)
    
    # Sort by credibility
    sources.sort(key=lambda s: s.credibility_score, reverse=True)
    
    # Generate synthesis
    synthesis = generate_synthesis(sources, req.query)
    
    # Select top sources for RAG (high credibility + diverse types)
    top_for_rag = [s.id for s in sources if s.credibility_score >= 0.7][:10]
    
    log.info(f"✅ Research complete: {len(sources)} sources, {len(top_for_rag)} recommended for RAG")
    
    return ResearchResponse(
        sources=sources,
        synthesis=synthesis,
        top_sources_for_rag=top_for_rag,
        query=req.query,
        total_found=len(sources)
    )

# ------------------------------------------------------------------
# UTILITY ENDPOINTS
# ------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "agent": "researcher",
        "status": "operational",
        "version": "1.0.0",
        "capabilities": ["web_search", "scholarly_search", "news_search", "synthesis"]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "custom_search": bool(custom_search_service),
        "semantic_scholar": bool(SEMANTIC_SCHOLAR_API_KEY),
        "news_api": bool(NEWS_API_KEY)
    }

@app.post("/fetch_pdf")
async def fetch_pdf(url: str):
    """Download and store a PDF for ingestion"""
    # TODO: Implement PDF download and storage
    raise HTTPException(501, "PDF fetching not yet implemented")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

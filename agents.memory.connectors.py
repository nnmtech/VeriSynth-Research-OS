"""
VeriSynthOS Memory Agent - Email & File Share Connectors
Monitors Gmail and network file shares for new documents
"""

import logging
import asyncio
import hashlib
import base64
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime, timezone

from fastapi import HTTPException, BackgroundTasks
from pydantic import BaseModel

log = logging.getLogger("memory.connectors")

# Global state
file_share_watchers = {}

# ------------------------------------------------------------------
# MODELS
# ------------------------------------------------------------------
class EmailWatchRequest(BaseModel):
    gmail_label: Optional[str] = "INBOX"
    max_results: int = 100

class FileShareWatchRequest(BaseModel):
    share_path: str  # SMB/NFS mount point
    watch_pattern: str = "**/*"  # Glob pattern
    poll_interval: int = 300  # seconds

# ------------------------------------------------------------------
# EMAIL MONITORING (Gmail API)
# ------------------------------------------------------------------
async def start_email_watch(req: EmailWatchRequest, credentials, db, extract_text, semantic_chunk, embed, now_iso):
    """
    Start monitoring Gmail inbox for attachments to ingest
    """
    if not credentials:
        raise HTTPException(503, "GCP credentials required for Gmail API")
    
    try:
        from googleapiclient.discovery import build
        gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        
        # List messages with attachments
        query = f"label:{req.gmail_label} has:attachment"
        results = gmail.users().messages().list(
            userId="me",
            q=query,
            maxResults=req.max_results
        ).execute()
        
        messages = results.get("messages", [])
        log.info(f"Found {len(messages)} emails with attachments")
        
        # Process attachments
        processed = await process_email_attachments(
            gmail, messages, db, extract_text, semantic_chunk, embed, now_iso
        )
        
        return {
            "status": "completed",
            "email_count": len(messages),
            "attachments_processed": processed,
            "label": req.gmail_label
        }
        
    except Exception as e:
        log.error(f"Email watch failed: {e}")
        raise HTTPException(500, str(e))

async def process_email_attachments(gmail, messages, db, extract_text, semantic_chunk, embed, now_iso):
    """Process attachments from Gmail messages"""
    processed_count = 0
    
    for msg in messages:
        try:
            message = gmail.users().messages().get(
                userId="me",
                id=msg["id"],
                format="full"
            ).execute()
            
            # Get email metadata
            headers = message.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
            date = next((h["value"] for h in headers if h["name"] == "Date"), "")
            
            # Extract attachments
            parts = message.get("payload", {}).get("parts", [])
            for part in parts:
                if part.get("filename"):
                    attachment_id = part.get("body", {}).get("attachmentId")
                    if attachment_id:
                        attachment = gmail.users().messages().attachments().get(
                            userId="me",
                            messageId=msg["id"],
                            id=attachment_id
                        ).execute()
                        
                        # Decode attachment
                        file_data = base64.urlsafe_b64decode(attachment["data"])
                        
                        # Process like any other file
                        content_hash = hashlib.sha256(file_data).hexdigest()
                        
                        # Check dedupe
                        existing = db.collection("memory_hashes").document(content_hash).get()
                        if existing.exists:
                            log.info(f"Duplicate email attachment: {part['filename']}")
                            continue
                        
                        # Extract and index
                        mime_type = part.get("mimeType", "application/octet-stream")
                        text = extract_text(file_data, mime_type)
                        
                        if text:
                            chunks = semantic_chunk(text)
                            embeddings = embed([c["text"] for c in chunks])
                            
                            # Store with email provenance
                            file_id = content_hash[:16]
                            db.collection("memory_docs").document(file_id).set({
                                "file_id": file_id,
                                "file_name": part["filename"],
                                "content_hash": content_hash,
                                "uploaded_at": now_iso(),
                                "chunk_count": len(chunks),
                                "source": "email",
                                "email_subject": subject,
                                "email_from": sender,
                                "email_date": date,
                                "email_message_id": msg["id"],
                                "deleted": False
                            })
                            
                            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                                db.collection("chunks").add({
                                    "document_id": file_id,
                                    "chunk_index": i,
                                    "text": chunk["text"],
                                    "token_count": chunk.get("token_count", 0),
                                    "embedding": emb,
                                    "created_at": now_iso()
                                })
                            
                            db.collection("memory_hashes").document(content_hash).set({
                                "file_id": file_id,
                                "file_name": part["filename"],
                                "indexed_at": now_iso()
                            })
                            
                            log.info(f"✅ Indexed email attachment: {part['filename']} from '{subject}'")
                            processed_count += 1
                            
        except Exception as e:
            log.error(f"Failed to process email {msg.get('id')}: {e}")
            continue
    
    return processed_count

# ------------------------------------------------------------------
# FILE SHARE MONITORING (SMB/NFS)
# ------------------------------------------------------------------
async def start_fileshare_watch(req: FileShareWatchRequest, db, process_local_file):
    """
    Start monitoring a network file share for new documents
    """
    if not db:
        raise HTTPException(503, "Firestore required")
    
    share_path = Path(req.share_path)
    
    if not share_path.exists():
        raise HTTPException(404, f"File share not found: {req.share_path}")
    
    if not share_path.is_dir():
        raise HTTPException(400, f"Path is not a directory: {req.share_path}")
    
    # Create watcher task
    watcher_id = hashlib.md5(req.share_path.encode()).hexdigest()
    
    if watcher_id in file_share_watchers:
        return {
            "status": "already_watching",
            "watcher_id": watcher_id,
            "path": req.share_path
        }
    
    # Start background polling task
    file_share_watchers[watcher_id] = {
        "path": req.share_path,
        "pattern": req.watch_pattern,
        "poll_interval": req.poll_interval,
        "last_check": {},
        "active": True
    }
    
    # Start polling in background
    asyncio.create_task(poll_file_share(watcher_id, process_local_file))
    
    log.info(f"Started file share watcher: {req.share_path}")
    
    return {
        "status": "watching",
        "watcher_id": watcher_id,
        "path": req.share_path,
        "poll_interval": req.poll_interval
    }

async def poll_file_share(watcher_id: str, process_local_file):
    """Background task to poll file share for changes"""
    watcher = file_share_watchers.get(watcher_id)
    if not watcher:
        return
    
    while watcher.get("active"):
        try:
            share_path = Path(watcher["path"])
            pattern = watcher["pattern"]
            last_check = watcher["last_check"]
            
            # Scan for files matching pattern
            for file_path in share_path.glob(pattern):
                if file_path.is_file():
                    # Check if file is new or modified
                    mtime = file_path.stat().st_mtime
                    file_key = str(file_path)
                    
                    if file_key not in last_check or last_check[file_key] < mtime:
                        # File is new or modified - ingest it
                        log.info(f"New/modified file detected: {file_path}")
                        
                        try:
                            chunks = process_local_file(str(file_path))
                            log.info(f"✅ Ingested {chunks} chunks from {file_path.name}")
                        except Exception as e:
                            log.error(f"Failed to ingest {file_path}: {e}")
                        
                        last_check[file_key] = mtime
            
            # Update last check time
            watcher["last_check"] = last_check
            
        except Exception as e:
            log.error(f"File share polling error: {e}")
        
        # Wait before next poll
        await asyncio.sleep(watcher["poll_interval"])
    
    log.info(f"File share watcher stopped: {watcher_id}")

async def stop_fileshare_watch(watcher_id: str):
    """Stop monitoring a file share"""
    if watcher_id not in file_share_watchers:
        raise HTTPException(404, "Watcher not found")
    
    file_share_watchers[watcher_id]["active"] = False
    del file_share_watchers[watcher_id]
    
    return {"status": "stopped", "watcher_id": watcher_id}

def list_fileshare_watchers():
    """List all active file share watchers"""
    return {
        "watchers": [
            {
                "watcher_id": wid,
                "path": info["path"],
                "pattern": info["pattern"],
                "poll_interval": info["poll_interval"],
                "files_tracked": len(info["last_check"])
            }
            for wid, info in file_share_watchers.items()
            if info.get("active")
        ]
    }

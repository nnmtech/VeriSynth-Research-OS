"""
Verifier Agent with voting wrapper.

Provides verification with multiple verifiers and consensus-based voting.
"""
import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from app.core.llm_router import LLMMessage, LLMRouter
from app.models.schemas import VerificationRequest, VerificationResult, VerificationVote

logger = structlog.get_logger(__name__)


class VerifierAgent:
    """
    Verifier Agent with voting-based consensus.

    Runs multiple verifiers in parallel and aggregates votes for robust verification.
    """

    def __init__(self, llm_router: LLMRouter | None = None) -> None:
        """Initialize Verifier Agent."""
        self.llm_router = llm_router or LLMRouter()
        self.logger = logger.bind(component="verifier_agent")

    async def verify(
        self,
        request: VerificationRequest,
        num_verifiers: int = 3,
    ) -> VerificationResult:
        """
        Verify content using multiple verifiers with voting.

        Args:
            request: Verification request
            num_verifiers: Number of verifiers to use

        Returns:
            VerificationResult with consensus
        """
        start_time = time.time()
        self.logger.info(
            "starting_verification",
            content_length=len(request.content),
            num_verifiers=num_verifiers,
        )

        # Create verification tasks
        tasks = [
            self._run_single_verifier(request, verifier_id=i)
            for i in range(num_verifiers)
        ]

        # Run verifiers in parallel
        votes = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_votes = [v for v in votes if isinstance(v, VerificationVote)]

        if not valid_votes:
            self.logger.error("all_verifiers_failed")
            raise RuntimeError("All verifiers failed")

        # Calculate consensus
        consensus = self._calculate_consensus(valid_votes)

        execution_time = time.time() - start_time

        self.logger.info(
            "verification_complete",
            verified=consensus["verified"],
            confidence=consensus["confidence"],
            execution_time=execution_time,
        )

        return VerificationResult(
            verified=consensus["verified"],
            confidence=consensus["confidence"],
            votes=valid_votes,
            consensus=consensus,
            execution_time=execution_time,
        )

    async def _run_single_verifier(
        self,
        request: VerificationRequest,
        verifier_id: int,
    ) -> VerificationVote:
        """
        Run a single verifier.

        Args:
            request: Verification request
            verifier_id: Verifier identifier

        Returns:
            VerificationVote
        """
        self.logger.debug("running_verifier", verifier_id=verifier_id)

        try:
            # Construct verification prompt
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are a verification agent. Analyze the provided content and "
                        "determine if it meets the verification criteria. Respond with a JSON "
                        "object containing: vote (true/false), confidence (0.0-1.0), and "
                        "reasoning (string)."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"Verification Type: {request.verification_type}\n\n"
                        f"Content to verify:\n{request.content}\n\n"
                        f"Context: {request.context}"
                    ),
                ),
            ]

            # Get LLM response
            response = await self.llm_router.complete(
                messages=messages,
                temperature=0.3,  # Lower temperature for consistency
                max_tokens=500,
            )

            # Parse response (simplified - in production, use structured output)
            # For now, use heuristics
            content = response.content.lower()
            vote = "true" in content or "verified" in content or "valid" in content

            # Extract confidence (simplified)
            confidence = 0.8 if vote else 0.6
            if "high confidence" in content:
                confidence = 0.95
            elif "low confidence" in content:
                confidence = 0.5

            return VerificationVote(
                verifier_id=f"verifier_{verifier_id}",
                vote=vote,
                confidence=confidence,
                reasoning=response.content[:500],
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            self.logger.error("verifier_failed", verifier_id=verifier_id, error=str(e))
            raise

    def _calculate_consensus(
        self,
        votes: list[VerificationVote],
    ) -> dict[str, Any]:
        """
        Calculate consensus from votes.

        Args:
            votes: List of verification votes

        Returns:
            Consensus dictionary
        """
        if not votes:
            return {
                "verified": False,
                "confidence": 0.0,
                "agreement_rate": 0.0,
                "total_votes": 0,
            }

        # Count votes
        positive_votes = sum(1 for v in votes if v.vote)
        negative_votes = len(votes) - positive_votes

        # Calculate weighted confidence
        positive_confidence = sum(v.confidence for v in votes if v.vote)
        negative_confidence = sum(v.confidence for v in votes if not v.vote)

        total_confidence = positive_confidence + negative_confidence

        # Determine consensus
        if positive_votes > negative_votes:
            verified = True
            confidence = positive_confidence / total_confidence if total_confidence > 0 else 0.0
        elif negative_votes > positive_votes:
            verified = False
            confidence = negative_confidence / total_confidence if total_confidence > 0 else 0.0
        else:
            # Tie - use confidence to break
            verified = positive_confidence >= negative_confidence
            confidence = 0.5

        agreement_rate = max(positive_votes, negative_votes) / len(votes)

        return {
            "verified": verified,
            "confidence": confidence,
            "agreement_rate": agreement_rate,
            "total_votes": len(votes),
            "positive_votes": positive_votes,
            "negative_votes": negative_votes,
            "positive_confidence": positive_confidence,
            "negative_confidence": negative_confidence,
        }

    async def verify_with_custom_verifiers(
        self,
        request: VerificationRequest,
        verifiers: list[Callable[..., Any]],
    ) -> VerificationResult:
        """
        Verify using custom verifier functions.

        Args:
            request: Verification request
            verifiers: List of async verifier functions

        Returns:
            VerificationResult with consensus
        """
        start_time = time.time()
        self.logger.info("custom_verification", num_verifiers=len(verifiers))

        # Run custom verifiers
        tasks = [verifier(request) for verifier in verifiers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert to votes
        votes = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                continue

            if isinstance(result, dict):
                votes.append(
                    VerificationVote(
                        verifier_id=f"custom_verifier_{i}",
                        vote=result.get("vote", False),
                        confidence=result.get("confidence", 0.5),
                        reasoning=result.get("reasoning", ""),
                        timestamp=datetime.utcnow(),
                    )
                )

        if not votes:
            raise RuntimeError("All custom verifiers failed")

        consensus = self._calculate_consensus(votes)
        execution_time = time.time() - start_time

        return VerificationResult(
            verified=consensus["verified"],
            confidence=consensus["confidence"],
            votes=votes,
            consensus=consensus,
            execution_time=execution_time,
        )

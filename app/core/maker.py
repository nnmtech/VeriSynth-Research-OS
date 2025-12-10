"""
MAKER (Massively Agentic Knowledge Evolution and Reasoning) implementation.

Implements first_to_ahead_by_k strategy with dynamic red-flagging for audit-ready systems.
Based on Meyerson et al. (2025) MDAP framework.
"""
import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

from app.core.config import get_settings

logger = structlog.get_logger(__name__)


class AgentStatus(str, Enum):
    """Agent execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RED_FLAGGED = "red_flagged"


@dataclass
class AgentResult:
    """Result from an agent execution."""
    agent_id: str
    status: AgentStatus
    output: Any
    confidence: float
    execution_time: float
    metadata: dict[str, Any]
    red_flags: list[str]


@dataclass
class MAKERConfig:
    """Configuration for MAKER execution."""
    k_value: int = 2  # Number of agents that must be ahead for first_to_ahead_by_k
    timeout_seconds: int = 300
    max_concurrent: int = 10
    red_flag_threshold: float = 0.3
    enable_dynamic_red_flagging: bool = True


class MAKER:
    """
    MAKER: Massively Agentic Knowledge Evolution and Reasoning.

    Coordinates multiple agents using first_to_ahead_by_k strategy with dynamic red-flagging.
    """

    def __init__(self, config: MAKERConfig | None = None) -> None:
        """Initialize MAKER with configuration."""
        settings = get_settings()
        self.config = config or MAKERConfig(
            k_value=settings.maker_k_value,
            timeout_seconds=settings.maker_timeout_seconds,
            max_concurrent=settings.maker_max_concurrent,
            red_flag_threshold=settings.maker_red_flag_threshold,
        )
        self.logger = logger.bind(component="maker")

    async def first_to_ahead_by_k(
        self,
        agents: list[Callable[..., Any]],
        agent_inputs: list[dict[str, Any]],
        k: int | None = None,
    ) -> AgentResult:
        """
        Execute agents using first_to_ahead_by_k strategy.

        Returns the result of the first agent to be ahead by k completions.

        Args:
            agents: List of async agent functions to execute
            agent_inputs: List of input dictionaries for each agent
            k: Number of agents that must be ahead (defaults to config.k_value)

        Returns:
            AgentResult from the winning agent
        """
        k = k or self.config.k_value

        if len(agents) != len(agent_inputs):
            raise ValueError("Number of agents must match number of inputs")

        if k >= len(agents):
            raise ValueError(f"k ({k}) must be less than number of agents ({len(agents)})")

        self.logger.info(
            "starting_first_to_ahead_by_k",
            num_agents=len(agents),
            k_value=k,
        )

        results: list[AgentResult | None] = [None] * len(agents)
        completion_order: list[int] = []

        async def run_agent(idx: int, agent: Callable[..., Any], inputs: dict[str, Any]) -> None:
            """Run a single agent and store result."""
            agent_id = f"agent_{idx}"
            start_time = time.time()

            try:
                self.logger.debug("agent_started", agent_id=agent_id)

                # Execute agent
                output = await agent(**inputs)
                execution_time = time.time() - start_time

                # Extract confidence and perform red-flag analysis
                confidence = self._extract_confidence(output)
                red_flags = []

                if self.config.enable_dynamic_red_flagging:
                    red_flags = await self._analyze_red_flags(output, inputs)

                # Determine status
                status = AgentStatus.COMPLETED
                if red_flags and confidence < self.config.red_flag_threshold:
                    status = AgentStatus.RED_FLAGGED
                    self.logger.warning(
                        "agent_red_flagged",
                        agent_id=agent_id,
                        red_flags=red_flags,
                        confidence=confidence,
                    )

                results[idx] = AgentResult(
                    agent_id=agent_id,
                    status=status,
                    output=output,
                    confidence=confidence,
                    execution_time=execution_time,
                    metadata={"completion_order": len(completion_order)},
                    red_flags=red_flags,
                )

                completion_order.append(idx)

                self.logger.info(
                    "agent_completed",
                    agent_id=agent_id,
                    execution_time=execution_time,
                    confidence=confidence,
                    status=status,
                )

            except Exception as e:
                execution_time = time.time() - start_time
                self.logger.error(
                    "agent_failed",
                    agent_id=agent_id,
                    error=str(e),
                    execution_time=execution_time,
                )
                results[idx] = AgentResult(
                    agent_id=agent_id,
                    status=AgentStatus.FAILED,
                    output=None,
                    confidence=0.0,
                    execution_time=execution_time,
                    metadata={"error": str(e)},
                    red_flags=[f"execution_error: {str(e)}"],
                )

        # Launch all agents concurrently with semaphore for max_concurrent
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        async def run_with_semaphore(idx: int, agent: Callable[..., Any], inputs: dict[str, Any]) -> None:
            async with semaphore:
                await run_agent(idx, agent, inputs)

        tasks = [
            asyncio.create_task(run_with_semaphore(i, agent, agent_inputs[i]))
            for i, agent in enumerate(agents)
        ]

        # Wait for first agent to be ahead by k
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                while len(completion_order) < len(agents):
                    await asyncio.sleep(0.1)

                    # Check if any agent is ahead by k
                    if len(completion_order) >= k + 1:
                        # First agent to complete while being ahead by k wins
                        winning_idx = completion_order[0]
                        winning_result = results[winning_idx]

                        if winning_result and winning_result.status != AgentStatus.RED_FLAGGED:
                            self.logger.info(
                                "winner_determined",
                                winner=winning_result.agent_id,
                                completion_order=winning_result.metadata["completion_order"],
                                k_value=k,
                            )

                            # Cancel remaining tasks
                            for task in tasks:
                                if not task.done():
                                    task.cancel()

                            return winning_result

        except TimeoutError:
            self.logger.error("maker_timeout", timeout=self.config.timeout_seconds)
            # Cancel all tasks
            for task in tasks:
                if not task.done():
                    task.cancel()

        # If we get here, either timeout or all agents completed
        # Return best non-red-flagged result
        valid_results = [r for r in results if r and r.status == AgentStatus.COMPLETED]

        if valid_results:
            best_result = max(valid_results, key=lambda r: r.confidence)
            self.logger.info("returning_best_result", agent_id=best_result.agent_id)
            return best_result

        # All failed or red-flagged - return first available result
        available_results = [r for r in results if r is not None]
        if available_results:
            return available_results[0]

        # Should never reach here, but handle gracefully
        raise RuntimeError("No agent results available")

    def _extract_confidence(self, output: Any) -> float:
        """Extract confidence score from agent output."""
        if isinstance(output, dict):
            return output.get("confidence", 0.5)
        return 0.5

    async def _analyze_red_flags(
        self,
        output: Any,
        inputs: dict[str, Any],
    ) -> list[str]:
        """
        Analyze output for red flags indicating potential issues.

        Red flags include:
        - Low confidence scores
        - Contradictory outputs
        - Missing required fields
        - Suspicious patterns
        """
        red_flags: list[str] = []

        if isinstance(output, dict):
            # Check for missing required fields
            required_fields = ["result", "reasoning"]
            for field in required_fields:
                if field not in output:
                    red_flags.append(f"missing_field: {field}")

            # Check for empty or very short reasoning
            reasoning = output.get("reasoning", "")
            if len(reasoning) < 10:
                red_flags.append("insufficient_reasoning")

            # Check for contradictory confidence
            confidence = output.get("confidence", 0.5)
            if confidence < self.config.red_flag_threshold:
                red_flags.append(f"low_confidence: {confidence}")

        return red_flags

    async def evaluate_consensus(
        self,
        agents: list[Callable[..., Any]],
        agent_inputs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Evaluate consensus across all agents.

        Returns aggregated results with voting and confidence metrics.
        """
        self.logger.info("evaluating_consensus", num_agents=len(agents))

        # Run all agents
        results: list[AgentResult] = []

        tasks = [
            self._run_single_agent(i, agent, agent_inputs[i])
            for i, agent in enumerate(agents)
        ]

        completed_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed_results:
            if isinstance(result, AgentResult):
                results.append(result)

        # Analyze consensus
        successful_results = [r for r in results if r.status == AgentStatus.COMPLETED]

        if not successful_results:
            return {
                "consensus_reached": False,
                "reason": "no_successful_agents",
                "total_agents": len(agents),
                "successful_agents": 0,
            }

        # Calculate metrics
        avg_confidence = sum(r.confidence for r in successful_results) / len(successful_results)

        return {
            "consensus_reached": len(successful_results) >= len(agents) * 0.6,
            "total_agents": len(agents),
            "successful_agents": len(successful_results),
            "average_confidence": avg_confidence,
            "results": [
                {
                    "agent_id": r.agent_id,
                    "confidence": r.confidence,
                    "execution_time": r.execution_time,
                }
                for r in successful_results
            ],
        }

    async def _run_single_agent(
        self,
        idx: int,
        agent: Callable[..., Any],
        inputs: dict[str, Any],
    ) -> AgentResult:
        """Run a single agent and return result."""
        agent_id = f"agent_{idx}"
        start_time = time.time()

        try:
            output = await agent(**inputs)
            execution_time = time.time() - start_time
            confidence = self._extract_confidence(output)

            return AgentResult(
                agent_id=agent_id,
                status=AgentStatus.COMPLETED,
                output=output,
                confidence=confidence,
                execution_time=execution_time,
                metadata={},
                red_flags=[],
            )
        except Exception as e:
            execution_time = time.time() - start_time
            return AgentResult(
                agent_id=agent_id,
                status=AgentStatus.FAILED,
                output=None,
                confidence=0.0,
                execution_time=execution_time,
                metadata={"error": str(e)},
                red_flags=[f"execution_error: {str(e)}"],
            )

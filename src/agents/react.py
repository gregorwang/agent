"""
ReAct (Reasoning + Acting) pattern implementation

This module implements the ReAct pattern for structured reasoning and action
execution with Claude Agent SDK.
"""

import json
from dataclasses import dataclass, field
from typing import AsyncIterator

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)


@dataclass
class ReActStep:
    """Represents a single ReAct step"""
    step_number: int
    thought: str
    action: str | None = None
    action_input: dict | None = None
    observation: str | None = None
    is_final: bool = False


@dataclass
class ReActTrace:
    """Complete trace of a ReAct execution"""
    goal: str
    steps: list[ReActStep] = field(default_factory=list)
    final_answer: str | None = None
    success: bool = False


class ReActController:
    """
    Controller for ReAct-style reasoning and acting.

    The ReAct pattern alternates between:
    1. Thought: Reasoning about the current state
    2. Action: Executing a tool or providing an answer
    3. Observation: Receiving the result of the action

    This continues until a final answer is reached or max steps exceeded.
    """

    REACT_PROMPT_TEMPLATE = """You are solving a task using the ReAct framework.

TASK: {goal}

You must follow this exact format for each step:

Thought: [Your reasoning about what to do next]
Action: [The tool to use OR "Final Answer" if done]
Action Input: [Input for the tool as JSON, or your final answer]

Rules:
1. Always start with a Thought
2. Be thorough but efficient
3. When you have enough information, provide the Final Answer
4. Use tools strategically to gather information
5. Each thought should build on previous observations

Previous steps:
{history}

Continue from where you left off. What is your next thought and action?"""

    def __init__(
        self,
        client: ClaudeSDKClient,
        max_steps: int = 10,
        verbose: bool = False
    ):
        """
        Initialize the ReAct controller.

        Args:
            client: Connected ClaudeSDKClient instance
            max_steps: Maximum number of reasoning steps
            verbose: Whether to print debug information
        """
        self.client = client
        self.max_steps = max_steps
        self.verbose = verbose

    async def run(
        self,
        goal: str,
        session_id: str = "react"
    ) -> ReActTrace:
        """
        Run the ReAct loop for a given goal.

        Args:
            goal: The task or question to solve
            session_id: Session identifier for the conversation

        Returns:
            ReActTrace containing all steps and the final answer
        """
        trace = ReActTrace(goal=goal)

        for step_num in range(1, self.max_steps + 1):
            step = await self._execute_step(goal, trace.steps, session_id)
            step.step_number = step_num
            trace.steps.append(step)

            if self.verbose:
                self._print_step(step)

            if step.is_final:
                trace.final_answer = step.observation
                trace.success = True
                break

        return trace

    async def _execute_step(
        self,
        goal: str,
        history: list[ReActStep],
        session_id: str
    ) -> ReActStep:
        """Execute a single ReAct step."""
        prompt = self._build_prompt(goal, history)
        step = ReActStep(step_number=len(history) + 1, thought="")

        await self.client.query(prompt, session_id=session_id)

        async for message in self.client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Parse thought from text
                        step.thought = self._extract_thought(block.text)

                    elif isinstance(block, ToolUseBlock):
                        step.action = block.name
                        step.action_input = block.input

                    elif isinstance(block, ToolResultBlock):
                        step.observation = block.content

            elif isinstance(message, ResultMessage):
                if message.result:
                    # Check if this is a final answer
                    if "Final Answer" in step.action if step.action else False:
                        step.is_final = True
                        step.observation = message.result
                    elif not step.observation:
                        step.observation = message.result

        return step

    def _build_prompt(self, goal: str, history: list[ReActStep]) -> str:
        """Build the prompt with history."""
        history_str = ""
        for step in history:
            history_str += f"\nStep {step.step_number}:\n"
            history_str += f"Thought: {step.thought}\n"
            if step.action:
                history_str += f"Action: {step.action}\n"
                if step.action_input:
                    history_str += f"Action Input: {json.dumps(step.action_input)}\n"
            if step.observation:
                obs = step.observation[:500] + "..." if len(step.observation) > 500 else step.observation
                history_str += f"Observation: {obs}\n"

        if not history_str:
            history_str = "(No previous steps)"

        return self.REACT_PROMPT_TEMPLATE.format(
            goal=goal,
            history=history_str
        )

    def _extract_thought(self, text: str) -> str:
        """Extract the thought portion from response text."""
        lines = text.strip().split("\n")
        thought_lines = []
        in_thought = False

        for line in lines:
            if line.startswith("Thought:"):
                in_thought = True
                thought_lines.append(line[8:].strip())
            elif line.startswith("Action:"):
                break
            elif in_thought:
                thought_lines.append(line.strip())

        return " ".join(thought_lines) if thought_lines else text[:200]

    def _print_step(self, step: ReActStep) -> None:
        """Print a step for debugging."""
        print(f"\n--- Step {step.step_number} ---")
        print(f"Thought: {step.thought}")
        if step.action:
            print(f"Action: {step.action}")
        if step.observation:
            print(f"Observation: {step.observation[:200]}...")


async def run_react(
    client: ClaudeSDKClient,
    goal: str,
    max_steps: int = 10,
    session_id: str = "react"
) -> ReActTrace:
    """
    Convenience function to run ReAct reasoning.

    Args:
        client: Connected ClaudeSDKClient instance
        goal: The task or question to solve
        max_steps: Maximum number of reasoning steps
        session_id: Session identifier

    Returns:
        ReActTrace containing all steps and the final answer
    """
    controller = ReActController(client, max_steps=max_steps)
    return await controller.run(goal, session_id)

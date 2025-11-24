"""
Base Agent class for all specialized agents in the multiagentic system
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from langchain_groq import ChatGroq
from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import Tool
from langchain.prompts import PromptTemplate
from langchain.schema import SystemMessage, HumanMessage
import json
import logging
import os
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all specialized agents"""
    
    def __init__(self, agent_name: str, github_token: str = None):
        self.agent_name = agent_name
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        # Use model with better rate limits - fallback to 70b if 8b hits limits
        # Try 8b first, but it has stricter rate limits
        self.model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")  # Default to 70b for better rate limits
        self.llm = ChatGroq(
            model=self.model_name,
            temperature=0.1,
            groq_api_key=groq_api_key,
            max_tokens=2000,
            request_timeout=60  # Increase timeout
        )
        
        self.tools = self._create_tools()
        self.agent_executor = self._create_agent_executor()
        self.analysis_depth = "extreme"  # For deep analysis
        
    @abstractmethod
    def _create_tools(self) -> List[Tool]:
        """Create agent-specific tools"""
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get agent-specific system prompt"""
        pass
    
    def _create_agent_executor(self) -> AgentExecutor:
        """Create the agent executor with ReAct framework"""
        system_context = self.get_system_prompt()
        template = f"""You are {self.agent_name}, a specialized AI agent with deep expertise in your domain.

{system_context}

You have access to the following tools:

{{tools}}

Use the following format:

Question: the input question you must answer
Thought: you should always think deeply about what to do
Action: the action to take, should be one of [{{tool_names}}]
Action Input: the input to the action (must be valid JSON string)
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {{input}}
Thought:{{agent_scratchpad}}"""

        prompt = PromptTemplate.from_template(template)
        
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )
        
        agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=False,  # Disable verbose for speed
            handle_parsing_errors=True,
            max_iterations=5,  # Reduced for speed (was 20)
            return_intermediate_steps=False  # Skip intermediate steps for speed
        )
        
        return agent_executor
    
    @abstractmethod
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform analysis and return results"""
        pass
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def invoke_llm(self, prompt: str, system_message: Optional[str] = None, max_tokens: int = 1500) -> str:
        """Helper method to invoke LLM with retry logic for rate limiting"""
        messages = []
        if system_message:
            # Use shorter system message for speed
            messages.append(SystemMessage(content=system_message[:500] + "..." if len(system_message) > 500 else system_message))
        # Truncate prompt if too long (keep first 3000 chars for speed)
        truncated_prompt = prompt[:3000] + "..." if len(prompt) > 3000 else prompt
        messages.append(HumanMessage(content=truncated_prompt))
        
        try:
            response = self.llm.invoke(messages)
            return response.content.strip()
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "rate limit" in error_str:
                logger.warning(f"Rate limit hit, waiting before retry...")
                time.sleep(5)  # Wait 5 seconds before retry
                raise  # Re-raise to trigger retry
            raise
    
    def parse_json_response(self, response_text: str) -> Any:
        """Parse JSON from LLM response"""
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON, returning raw text")
            return response_text


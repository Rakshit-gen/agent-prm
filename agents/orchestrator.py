"""
Agent Orchestrator - Coordinates multiple specialized agents
"""
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import json
from datetime import datetime

from .security_agent import SecurityAgent
from .performance_agent import PerformanceAgent
from .architecture_agent import ArchitectureAgent
from .quality_agent import QualityAgent

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates multiple specialized agents for comprehensive analysis"""
    
    def __init__(self, github_token: str = None, progress_callback: Optional[Callable] = None):
        self.github_token = github_token
        self.progress_callback = progress_callback
        
        # Initialize all agents
        self.agents = {
            "security": SecurityAgent(github_token),
            "performance": PerformanceAgent(github_token),
            "architecture": ArchitectureAgent(github_token),
            "quality": QualityAgent(github_token)
        }
        
        self.agent_names = {
            "security": "Security Agent",
            "performance": "Performance Agent",
            "architecture": "Architecture Agent",
            "quality": "Quality Agent"
        }
    
    def _update_progress(self, agent_name: str, status: str, progress: float, message: str = ""):
        """Update progress via callback"""
        if self.progress_callback:
            self.progress_callback({
                "agent": agent_name,
                "status": status,  # "starting", "analyzing", "completed", "error"
                "progress": progress,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    def analyze_pr(self, pr_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Orchestrate multi-agent analysis of a PR
        
        Args:
            pr_data: Dictionary containing PR information with 'files' list
            
        Returns:
            Comprehensive analysis results from all agents
        """
        files = pr_data.get("files", [])
        context = {"files": files}
        
        results = {
            "pr_title": pr_data.get("pr_title", ""),
            "pr_url": pr_data.get("pr_url", ""),
            "analyzed_at": datetime.utcnow().isoformat(),
            "agents": {},
            "summary": {
                "total_agents": len(self.agents),
                "agents_completed": 0,
                "total_issues": 0,
                "critical_issues": 0,
                "high_priority_issues": 0
            },
            "files": []
        }
        
        # Run agents in parallel for efficiency
        with ThreadPoolExecutor(max_workers=len(self.agents)) as executor:
            futures = {}
            
            # Start all agents
            for agent_key, agent in self.agents.items():
                agent_name = self.agent_names[agent_key]
                self._update_progress(agent_name, "starting", 0.0, f"{agent_name} initialized")
                
                future = executor.submit(self._run_agent, agent, agent_key, context)
                futures[future] = agent_key
            
            # Collect results as they complete
            for future in as_completed(futures):
                agent_key = futures[future]
                agent_name = self.agent_names[agent_key]
                
                try:
                    self._update_progress(agent_name, "analyzing", 0.5, f"{agent_name} analyzing...")
                    agent_result = future.result()
                    results["agents"][agent_key] = agent_result
                    results["summary"]["agents_completed"] += 1
                    
                    # Update summary statistics
                    if "summary" in agent_result:
                        agent_summary = agent_result["summary"]
                        if "total_issues" in agent_summary:
                            results["summary"]["total_issues"] += agent_summary["total_issues"]
                        if "critical" in agent_summary:
                            results["summary"]["critical_issues"] += agent_summary["critical"]
                        if "high" in agent_summary:
                            results["summary"]["high_priority_issues"] += agent_summary["high"]
                        if "high_severity" in agent_summary:
                            results["summary"]["high_priority_issues"] += agent_summary["high_severity"]
                        if "high_impact" in agent_summary:
                            results["summary"]["high_priority_issues"] += agent_summary["high_impact"]
                    
                    self._update_progress(agent_name, "completed", 1.0, f"{agent_name} completed")
                    
                except Exception as e:
                    logger.error(f"Agent {agent_key} failed: {str(e)}")
                    results["agents"][agent_key] = {
                        "agent": agent_key,
                        "error": str(e),
                        "issues": [],
                        "summary": {}
                    }
                    self._update_progress(agent_name, "error", 0.0, f"{agent_name} failed: {str(e)}")
        
        # Aggregate issues by file
        file_issues_map = {}
        
        for agent_key, agent_result in results["agents"].items():
            issues = agent_result.get("issues", [])
            for issue in issues:
                filename = issue.get("file", "unknown")
                if filename not in file_issues_map:
                    file_issues_map[filename] = {
                        "name": filename,
                        "issues": [],
                        "agent_breakdown": {}
                    }
                
                # Add agent context to issue
                issue_with_agent = issue.copy()
                issue_with_agent["detected_by"] = agent_key
                file_issues_map[filename]["issues"].append(issue_with_agent)
                
                # Track by agent
                if agent_key not in file_issues_map[filename]["agent_breakdown"]:
                    file_issues_map[filename]["agent_breakdown"][agent_key] = 0
                file_issues_map[filename]["agent_breakdown"][agent_key] += 1
        
        # Convert to list format
        results["files"] = list(file_issues_map.values())
        
        # Final summary
        results["summary"]["total_files"] = len(results["files"])
        
        return results
    
    def _run_agent(self, agent, agent_key: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single agent and return results"""
        try:
            return agent.analyze(context)
        except Exception as e:
            logger.error(f"Error running agent {agent_key}: {str(e)}")
            return {
                "agent": agent_key,
                "error": str(e),
                "issues": [],
                "summary": {}
            }
    
    def get_agent_status(self) -> Dict[str, Any]:
        """Get status of all agents"""
        return {
            "total_agents": len(self.agents),
            "agents": {
                agent_key: {
                    "name": self.agent_names[agent_key],
                    "status": "ready"
                }
                for agent_key in self.agents.keys()
            }
        }


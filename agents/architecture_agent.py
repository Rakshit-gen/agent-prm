"""
Architecture Agent - Specialized in code architecture and design patterns
OPTIMIZED FOR SPEED: Combined checks, parallel execution
"""
from typing import Dict, Any, List
from langchain.tools import Tool
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ArchitectureAgent(BaseAgent):
    """Agent specialized in architecture analysis - OPTIMIZED VERSION"""
    
    def __init__(self, github_token: str = None):
        super().__init__("ArchitectureAgent", github_token)
    
    def get_system_prompt(self) -> str:
        return """Architecture expert. Check: design patterns, SOLID principles, coupling, scalability, separation of concerns. Return JSON array only."""
    
    def _create_tools(self) -> List[Tool]:
        return [
            Tool(
                name="comprehensive_architecture_analysis",
                func=self._comprehensive_analysis,
                description="Comprehensive architecture analysis. Input: JSON with 'code' and 'filename'"
            )
        ]
    
    def _comprehensive_analysis(self, input_str: str) -> str:
        """Combined architecture analysis - all checks in one LLM call"""
        try:
            data = json.loads(input_str)
            code = data.get("code", "")
            filename = data.get("filename", "")
            
            prompt = f"""Analyze this code for ALL architecture issues in ONE pass:

File: {filename}
Code (first 2000 chars): {code[:2000]}

Check for: design patterns (good/bad/missing), SOLID violations, coupling issues, scalability concerns, separation of concerns.

Return ONLY valid JSON array:
[{{"type": "architecture", "issue": "pattern|solid|coupling|scalability|separation", "line": number, "description": "...", "suggestion": "...", "severity": "high|medium|low"}}]

Be concise. Max 8 issues."""
            
            response = self.invoke_llm(prompt, self.get_system_prompt(), max_tokens=1000)
            return self.parse_json_response(response)
        except Exception as e:
            logger.error(f"Architecture analysis error: {e}")
            return json.dumps([])
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive architecture analysis - OPTIMIZED with parallel processing"""
        files = context.get("files", [])
        all_issues = []
        
        # Process files in parallel
        with ThreadPoolExecutor(max_workers=min(5, len(files))) as executor:
            futures = {}
            for file_data in files:
                filename = file_data.get("filename", "")
                code = file_data.get("patch", "") or file_data.get("code", "")
                
                if not code:
                    continue
                
                future = executor.submit(self._analyze_file, filename, code)
                futures[future] = filename
            
            for future in as_completed(futures):
                try:
                    file_issues = future.result()
                    all_issues.extend(file_issues)
                except Exception as e:
                    logger.error(f"Error analyzing file: {e}")
        
        return {
            "agent": "ArchitectureAgent",
            "issues": all_issues,
            "summary": {
                "total_issues": len(all_issues),
                "high_severity": sum(1 for i in all_issues if i.get("severity") == "high"),
                "medium_severity": sum(1 for i in all_issues if i.get("severity") == "medium"),
                "low_severity": sum(1 for i in all_issues if i.get("severity") == "low")
            }
        }
    
    def _analyze_file(self, filename: str, code: str) -> List[Dict[str, Any]]:
        """Analyze a single file"""
        logger.info(f"ArchitectureAgent: Analyzing {filename}")
        
        result = self._comprehensive_analysis(json.dumps({"code": code, "filename": filename}))
        
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                return parsed if isinstance(parsed, list) else []
            except:
                return []
        elif isinstance(result, list):
            return result
        return []

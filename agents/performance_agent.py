"""
Performance Agent - Specialized in performance optimization and analysis
OPTIMIZED FOR SPEED: Combined checks, parallel execution
"""
from typing import Dict, Any, List
from langchain.tools import Tool
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class PerformanceAgent(BaseAgent):
    """Agent specialized in performance analysis - OPTIMIZED VERSION"""
    
    def __init__(self, github_token: str = None):
        super().__init__("PerformanceAgent", github_token)
    
    def get_system_prompt(self) -> str:
        return """Performance expert. Find: complexity issues, N+1 queries, memory leaks, caching opportunities, blocking ops. Return JSON array only."""
    
    def _create_tools(self) -> List[Tool]:
        return [
            Tool(
                name="comprehensive_performance_analysis",
                func=self._comprehensive_analysis,
                description="Comprehensive performance analysis. Input: JSON with 'code', 'filename', and 'language'"
            )
        ]
    
    def _comprehensive_analysis(self, input_str: str) -> str:
        """Combined performance analysis - all checks in one LLM call"""
        try:
            data = json.loads(input_str)
            code = data.get("code", "")
            filename = data.get("filename", "")
            language = data.get("language", "unknown")
            
            prompt = f"""Analyze this {language} code for ALL performance issues in ONE pass:

File: {filename}
Code (first 2000 chars): {code[:2000]}

Check for: time/space complexity, N+1 queries, memory leaks, missing caching, blocking operations, inefficient algorithms.

Return ONLY valid JSON array:
[{{"type": "performance", "issue": "complexity|n_plus_one|memory|caching|blocking", "line": number, "description": "...", "suggestion": "...", "impact": "high|medium|low"}}]

Be concise. Max 8 issues."""
            
            response = self.invoke_llm(prompt, self.get_system_prompt(), max_tokens=1000)
            return self.parse_json_response(response)
        except Exception as e:
            logger.error(f"Performance analysis error: {e}")
            return json.dumps([])
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive performance analysis - OPTIMIZED with parallel processing"""
        files = context.get("files", [])
        all_issues = []
        
        # Process files in parallel
        with ThreadPoolExecutor(max_workers=min(5, len(files))) as executor:
            futures = {}
            for file_data in files:
                filename = file_data.get("filename", "")
                code = file_data.get("patch", "") or file_data.get("code", "")
                language = filename.split(".")[-1] if "." in filename else "unknown"
                
                if not code:
                    continue
                
                future = executor.submit(self._analyze_file, filename, code, language)
                futures[future] = filename
            
            for future in as_completed(futures):
                try:
                    file_issues = future.result()
                    all_issues.extend(file_issues)
                except Exception as e:
                    logger.error(f"Error analyzing file: {e}")
        
        return {
            "agent": "PerformanceAgent",
            "issues": all_issues,
            "summary": {
                "total_issues": len(all_issues),
                "high_impact": sum(1 for i in all_issues if i.get("impact") == "high"),
                "medium_impact": sum(1 for i in all_issues if i.get("impact") == "medium"),
                "low_impact": sum(1 for i in all_issues if i.get("impact") == "low")
            }
        }
    
    def _analyze_file(self, filename: str, code: str, language: str) -> List[Dict[str, Any]]:
        """Analyze a single file"""
        logger.info(f"PerformanceAgent: Analyzing {filename}")
        
        result = self._comprehensive_analysis(json.dumps({"code": code, "filename": filename, "language": language}))
        
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                return parsed if isinstance(parsed, list) else []
            except:
                return []
        elif isinstance(result, list):
            return result
        return []

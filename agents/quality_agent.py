"""
Quality Agent - Specialized in code quality, maintainability, and best practices
OPTIMIZED FOR SPEED: Combined checks, parallel execution
"""
from typing import Dict, Any, List
from langchain.tools import Tool
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class QualityAgent(BaseAgent):
    """Agent specialized in code quality - OPTIMIZED VERSION"""
    
    def __init__(self, github_token: str = None):
        super().__init__("QualityAgent", github_token)
    
    def get_system_prompt(self) -> str:
        return """Code quality expert. Find: code smells, readability issues, duplication, complexity, error handling, naming. Return JSON array only."""
    
    def _create_tools(self) -> List[Tool]:
        return [
            Tool(
                name="comprehensive_quality_analysis",
                func=self._comprehensive_analysis,
                description="Comprehensive quality analysis. Input: JSON with 'code' and 'filename'"
            )
        ]
    
    def _comprehensive_analysis(self, input_str: str) -> str:
        """Combined quality analysis - all checks in one LLM call"""
        try:
            data = json.loads(input_str)
            code = data.get("code", "")
            filename = data.get("filename", "")
            
            prompt = f"""Analyze this code for ALL quality issues in ONE pass:

File: {filename}
Code (first 2000 chars): {code[:2000]}

Check for: code smells (long methods, large classes), readability, duplication, complexity, error handling, naming.

Return ONLY valid JSON array:
[{{"type": "quality", "issue": "smell|readability|duplication|complexity|error_handling|naming", "line": number, "description": "...", "suggestion": "...", "severity": "high|medium|low"}}]

Be concise. Max 8 issues."""
            
            response = self.invoke_llm(prompt, self.get_system_prompt(), max_tokens=1000)
            return self.parse_json_response(response)
        except Exception as e:
            logger.error(f"Quality analysis error: {e}")
            return json.dumps([])
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive quality analysis - OPTIMIZED with parallel processing"""
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
            "agent": "QualityAgent",
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
        logger.info(f"QualityAgent: Analyzing {filename}")
        
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

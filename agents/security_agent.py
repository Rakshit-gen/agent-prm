"""
Security Agent - Specialized in detecting vulnerabilities and security issues
OPTIMIZED FOR SPEED: Combined checks, parallel execution, faster model
"""
from typing import Dict, Any, List
from langchain.tools import Tool
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class SecurityAgent(BaseAgent):
    """Agent specialized in security vulnerability detection - OPTIMIZED VERSION"""
    
    def __init__(self, github_token: str = None):
        super().__init__("SecurityAgent", github_token)
    
    def get_system_prompt(self) -> str:
        return """Security expert. Find vulnerabilities: injections, auth flaws, secrets, crypto issues, API security. Return JSON array only."""
    
    def _create_tools(self) -> List[Tool]:
        # Simplified tools for speed
        return [
            Tool(
                name="comprehensive_security_scan",
                func=self._comprehensive_scan,
                description="Comprehensive security scan combining all checks. Input: JSON with 'code' and 'filename'"
            )
        ]
    
    def _comprehensive_scan(self, input_str: str) -> str:
        """Combined security scan - all checks in one LLM call for speed"""
        try:
            data = json.loads(input_str)
            code = data.get("code", "")
            filename = data.get("filename", "")
            
            # Quick pattern-based secret detection (no LLM needed)
            secrets_found = self._quick_secret_scan(code)
            
            # Combined LLM prompt for all security checks
            prompt = f"""Analyze this code for ALL security issues in ONE pass:

File: {filename}
Code (first 2000 chars): {code[:2000]}

Check for: injections (SQL/XSS/command), auth flaws, crypto weaknesses, API security issues.

Return ONLY valid JSON array:
[{{"type": "security", "subtype": "injection|auth|secret|crypto|api", "severity": "critical|high|medium|low", "line": number, "description": "...", "suggestion": "..."}}]

Be concise. Max 10 issues."""
            
            response = self.invoke_llm(prompt, self.get_system_prompt(), max_tokens=1000)
            issues = self.parse_json_response(response)
            
            # Combine pattern-based and LLM results
            if isinstance(issues, list):
                issues.extend(secrets_found)
            elif isinstance(issues, str):
                issues = secrets_found
            
            return json.dumps(issues if isinstance(issues, list) else [])
        except Exception as e:
            logger.error(f"Security scan error: {e}")
            return json.dumps([])
    
    def _quick_secret_scan(self, code: str) -> List[Dict[str, Any]]:
        """Fast pattern-based secret detection (no LLM)"""
        patterns = {
            "api_key": (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']([^"\']{10,})["\']', "critical"),
            "password": (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']([^"\']+)["\']', "critical"),
            "token": (r'(?i)(token|secret|secret[_-]?key)\s*[=:]\s*["\']([^"\']{10,})["\']', "critical"),
            "aws_key": (r'AKIA[0-9A-Z]{16}', "critical"),
            "private_key": (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "critical")
        }
        
        issues = []
        for pattern_type, (pattern, severity) in patterns.items():
            matches = re.finditer(pattern, code)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                issues.append({
                    "type": "security",
                    "subtype": "secret_exposure",
                    "severity": severity,
                    "line": line_num,
                    "description": f"Potential {pattern_type} exposure detected",
                    "suggestion": "Move to environment variables or secure vault"
                })
        return issues
    
    def analyze(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive security analysis - OPTIMIZED with parallel file processing"""
        files = context.get("files", [])
        all_issues = []
        
        # Process files in parallel for speed
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
            "agent": "SecurityAgent",
            "issues": all_issues,
            "summary": {
                "total_issues": len(all_issues),
                "critical": sum(1 for i in all_issues if i.get("severity") == "critical"),
                "high": sum(1 for i in all_issues if i.get("severity") == "high"),
                "medium": sum(1 for i in all_issues if i.get("severity") == "medium"),
                "low": sum(1 for i in all_issues if i.get("severity") == "low")
            }
        }
    
    def _sanitize_issues(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sanitize issues to ensure valid line numbers"""
        sanitized = []
        for issue in issues:
            # Convert 0 or negative line numbers to None
            if "line" in issue and issue["line"] is not None:
                if issue["line"] < 1 or issue["line"] == 0:
                    issue["line"] = None
            # Ensure file field exists
            if "file" not in issue or not issue["file"]:
                issue["file"] = "unknown"
            sanitized.append(issue)
        return sanitized
    
    def _analyze_file(self, filename: str, code: str) -> List[Dict[str, Any]]:
        """Analyze a single file"""
        logger.info(f"SecurityAgent: Analyzing {filename}")
        
        result = self._comprehensive_scan(json.dumps({"code": code, "filename": filename}))
        
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, list):
                    # Add filename to issues and sanitize
                    for issue in parsed:
                        if "file" not in issue:
                            issue["file"] = filename
                    return self._sanitize_issues(parsed)
                return []
            except:
                return []
        elif isinstance(result, list):
            # Add filename to issues and sanitize
            for issue in result:
                if "file" not in issue:
                    issue["file"] = filename
            return self._sanitize_issues(result)
        return []

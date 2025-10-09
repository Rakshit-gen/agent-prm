import os
import requests
from typing import Dict, Any
import logging
from datetime import datetime
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CodeReviewAgent:
    def __init__(self, github_token: str = None):
        self.github_token = github_token or os.getenv('GITHUB_TOKEN')
        
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        try:
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=openai_api_key)
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            raise
        
        self.headers = {}
        if self.github_token:
            self.headers['Authorization'] = f'token {self.github_token}'
        
    def fetch_pr_data(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        parts = repo_url.rstrip('/').split('github.com/')[-1].split('/')
        owner = parts[0]
        repo = parts[1]
        
        logger.info(f"Fetching PR data for {owner}/{repo} #{pr_number}")
        
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        response = requests.get(pr_url, headers=self.headers)
        response.raise_for_status()
        pr_data = response.json()
        
        files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
        response = requests.get(files_url, headers=self.headers)
        response.raise_for_status()
        files_data = response.json()
        
        return {
            'pr': pr_data,
            'files': files_data
        }
    
    def analyze_file_diff(self, file_data: Dict[str, Any]) -> Dict[str, Any]:
        filename = file_data.get('filename', '')
        patch = file_data.get('patch', '')
        
        if not patch:
            return {
                'name': filename,
                'issues': []
            }
        
        logger.info(f"Analyzing file: {filename}")
        
        prompt = f"""You are a STRICT code reviewer. Analyze this code diff and find ALL issues, even minor ones.

File: {filename}
Diff:
{patch}

Check for:
1. **Style Issues:** spacing, naming conventions (PEP 8 for Python), line length (>80 chars), missing docstrings
2. **Bugs:** division by zero, null/None checks, exception handling, logic errors
3. **Performance:** inefficient loops, redundant operations, memory issues
4. **Best Practices:** missing type hints, poor variable names, code smells, magic numbers

Be CRITICAL and thorough. Even minor style issues should be reported.

Return a JSON array with ALL issues found:
[
  {{"type": "style", "line": 15, "description": "Missing space after comma", "suggestion": "Add space: x, y instead of x,y"}},
  {{"type": "bug", "line": 23, "description": "Potential division by zero", "suggestion": "Add check: if y != 0"}},
  {{"type": "style", "line": 30, "description": "Class name should use PascalCase", "suggestion": "Rename myClass to MyClass"}},
  {{"type": "best_practice", "line": 10, "description": "Missing docstring", "suggestion": "Add function docstring"}}
]

If truly no issues exist, return [abcdd]. But be thorough - look for ANY violations of coding standards. also give ai review of the pr about how do you judge it to be. rate it out of 10"""

        try:
            completion = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a STRICT, critical code reviewer who finds ALL issues. Always look for style violations, bugs, and best practice violations. Be thorough and pedantic. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=2048
            )
            
            response_text = completion.choices[0].message.content.strip()
            
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            issues = json.loads(response_text)
            
            return {
                'name': filename,
                'issues': issues if isinstance(issues, list) else []
            }
        except Exception as e:
            logger.error(f"Error analyzing file {filename}: {str(e)}")
            return {
                'name': filename,
                'issues': [],
                'error': str(e)
            }
    
    def analyze_pr(self, repo_url: str, pr_number: int) -> Dict[str, Any]:
        try:
            pr_data = self.fetch_pr_data(repo_url, pr_number)
            
            analyzed_files = []
            total_issues = 0
            critical_issues = 0
            
            for file_data in pr_data['files']:
                file_analysis = self.analyze_file_diff(file_data)
                analyzed_files.append(file_analysis)
                
                for issue in file_analysis.get('issues', []):
                    total_issues += 1
                    if issue.get('type') in ['bug', 'security']:
                        critical_issues += 1
            
            return {
                'pr_title': pr_data['pr'].get('title', ''),
                'pr_url': pr_data['pr'].get('html_url', ''),
                'analyzed_at': datetime.utcnow().isoformat(),
                'files': analyzed_files,
                'summary': {
                    'total_files': len(analyzed_files),
                    'total_issues': total_issues,
                    'critical_issues': critical_issues
                }
            }
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching PR data: {str(e)}")
            raise Exception(f"Failed to fetch PR data: {str(e)}")
        except Exception as e:
            logger.error(f"Error in analyze_pr: {str(e)}")
            raise
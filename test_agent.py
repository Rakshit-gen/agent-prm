import pytest
from unittest.mock import patch, MagicMock
from agent import CodeReviewAgent

@pytest.fixture
def agent():
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
        return CodeReviewAgent(github_token='test-token')

@patch('agent.requests.get')
def test_fetch_pr_data(mock_get, agent):
    mock_pr_response = MagicMock()
    mock_pr_response.json.return_value = {
        'title': 'Test PR',
        'html_url': 'https://github.com/test/repo/pull/1'
    }
    mock_pr_response.raise_for_status = MagicMock()
    
    mock_files_response = MagicMock()
    mock_files_response.json.return_value = [
        {'filename': 'test.py', 'patch': 'diff content'}
    ]
    mock_files_response.raise_for_status = MagicMock()
    
    mock_get.side_effect = [mock_pr_response, mock_files_response]
    
    result = agent.fetch_pr_data('https://github.com/test/repo', 1)
    
    assert 'pr' in result
    assert 'files' in result
    assert result['pr']['title'] == 'Test PR'

def test_analyze_file_diff_empty_patch(agent):
    file_data = {'filename': 'test.py', 'patch': ''}
    result = agent.analyze_file_diff(file_data)
    
    assert result['name'] == 'test.py'
    assert result['issues'] == []

@patch('agent.anthropic.Anthropic')
def test_analyze_file_diff_with_issues(mock_anthropic_class, agent):
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_content = MagicMock()
    mock_content.text = '[{"type": "style", "line": 10, "description": "Test issue", "suggestion": "Fix it"}]'
    mock_message.content = [mock_content]
    mock_client.messages.create.return_value = mock_message
    agent.anthropic_client = mock_client
    
    file_data = {
        'filename': 'test.py',
        'patch': '@@ -1,3 +1,3 @@\n-old line\n+new line'
    }
    
    result = agent.analyze_file_diff(file_data)
    
    assert result['name'] == 'test.py'
    assert len(result['issues']) == 1
    assert result['issues'][0]['type'] == 'style'

@patch('agent.CodeReviewAgent.fetch_pr_data')
@patch('agent.CodeReviewAgent.analyze_file_diff')
def test_analyze_pr(mock_analyze_file, mock_fetch_pr, agent):
    mock_fetch_pr.return_value = {
        'pr': {
            'title': 'Test PR',
            'html_url': 'https://github.com/test/repo/pull/1'
        },
        'files': [
            {'filename': 'test.py', 'patch': 'diff'}
        ]
    }
    
    mock_analyze_file.return_value = {
        'name': 'test.py',
        'issues': [
            {'type': 'bug', 'line': 10, 'description': 'Bug', 'suggestion': 'Fix'}
        ]
    }
    
    result = agent.analyze_pr('https://github.com/test/repo', 1)
    
    assert 'files' in result
    assert 'summary' in result
    assert result['summary']['total_files'] == 1
    assert result['summary']['total_issues'] == 1
    assert result['summary']['critical_issues'] == 1
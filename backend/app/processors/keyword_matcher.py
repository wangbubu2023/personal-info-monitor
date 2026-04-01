"""Keyword matching for content."""

import re
from typing import Any, Dict, List

from app.models import Keyword
from app.utils.logger import get_logger

logger = get_logger(__name__)
MAX_REGEX_LENGTH = 256
_UNSAFE_REGEX_PATTERNS = (
    (re.compile(r"\\[1-9]"), "backreferences are disallowed"),
    (re.compile(r"\(\?<([=!])"), "lookbehind assertions are disallowed"),
    (
        re.compile(r"\((?:[^()\\]|\\.)+\)(?:\+|\*|\{\d+(?:,\d*)?\})(?:\+|\*|\{\d+(?:,\d*)?\})"),
        "nested quantified groups are disallowed",
    ),
)


class KeywordMatcher:
    """Match keywords in content."""
    
    def match(
        self,
        text: str,
        keywords: List[Keyword]
    ) -> List[Dict[str, Any]]:
        """
        Match keywords in text.
        
        Args:
            text: Text to search in
            keywords: List of Keyword model instances
        
        Returns:
            List of matched keywords with metadata
        """
        if not text or not keywords:
            return []
        
        matches = []
        
        for keyword in keywords:
            if not keyword.enabled:
                continue
            
            is_match = self._check_match(text, keyword)
            
            if is_match:
                matches.append({
                    "id": str(keyword.id),
                    "keyword": keyword.keyword,
                    "color": keyword.color,
                    "match_type": keyword.match_type
                })
                logger.debug(f"Matched keyword: {keyword.keyword}")
        
        return matches
    
    def _check_match(self, text: str, keyword: Keyword) -> bool:
        """Check if keyword matches in text."""
        search_text = text if keyword.case_sensitive else text.lower()
        search_keyword = keyword.keyword if keyword.case_sensitive else keyword.keyword.lower()
        
        if keyword.match_type == "exact":
            # Exact word match
            pattern = rf'\b{re.escape(search_keyword)}\b'
            return bool(re.search(pattern, search_text))
        
        elif keyword.match_type == "contains":
            # Simple substring match
            return search_keyword in search_text
        
        elif keyword.match_type == "regex":
            # Regex match
            is_safe, reason = self._validate_regex_pattern(keyword.keyword)
            if not is_safe:
                logger.warning("Rejected unsafe regex pattern '%s': %s", keyword.keyword, reason)
                return False
            try:
                flags = 0 if keyword.case_sensitive else re.IGNORECASE
                return bool(re.search(keyword.keyword, text, flags))
            except re.error as e:
                logger.error(f"Invalid regex pattern '{keyword.keyword}': {e}")
                return False
        
        return False

    def _validate_regex_pattern(self, pattern: str) -> tuple[bool, str]:
        """Reject regex features that are common ReDoS footguns for user input."""
        candidate = str(pattern or "")
        if not candidate:
            return False, "pattern is empty"
        if len(candidate) > MAX_REGEX_LENGTH:
            return False, f"pattern exceeds {MAX_REGEX_LENGTH} characters"

        for compiled, reason in _UNSAFE_REGEX_PATTERNS:
            if compiled.search(candidate):
                return False, reason

        try:
            re.compile(candidate)
        except re.error as exc:
            return False, f"invalid regex: {exc}"

        return True, "ok"
    
    def highlight_matches(
        self,
        text: str,
        matches: List[Dict[str, Any]],
        tag: str = "mark"
    ) -> str:
        """
        Add HTML highlighting to matched keywords in text.
        
        Args:
            text: Original text
            matches: List of matched keywords from match()
            tag: HTML tag to use for highlighting
        
        Returns:
            Text with highlighted keywords
        """
        if not matches:
            return text
        
        highlighted = text
        
        # Sort by length (longest first) to handle overlapping matches
        sorted_matches = sorted(matches, key=lambda x: len(x["keyword"]), reverse=True)
        
        for match in sorted_matches:
            keyword = match["keyword"]
            color = match.get("color", "#ff4d4f")
            
            # Create case-insensitive pattern that preserves original case
            pattern = re.compile(re.escape(keyword), re.IGNORECASE)
            
            def replace_func(m):
                return f'<{tag} style="background-color: {color}; padding: 0 2px;">{m.group()}</{tag}>'
            
            highlighted = pattern.sub(replace_func, highlighted)
        
        return highlighted
    
    def get_match_context(
        self,
        text: str,
        keyword: str,
        context_chars: int = 100
    ) -> List[str]:
        """
        Get text snippets around keyword matches.
        
        Args:
            text: Text to search in
            keyword: Keyword to find
            context_chars: Number of characters of context on each side
        
        Returns:
            List of context snippets
        """
        contexts = []
        
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        
        for match in pattern.finditer(text):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            
            snippet = text[start:end]
            
            # Add ellipsis if truncated
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            
            contexts.append(snippet)
        
        return contexts

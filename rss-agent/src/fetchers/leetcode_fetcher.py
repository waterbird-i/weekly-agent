"""
LeetCode 题目抓取模块
从 LeetCode 获取随机题目用于 Weekly 训练部分
"""

import random
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import requests

logger = logging.getLogger(__name__)


@dataclass
class LeetCodeProblem:
    """LeetCode 题目数据类"""
    title: str
    title_cn: str
    difficulty: str
    url: str
    slug: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "title_cn": self.title_cn,
            "difficulty": self.difficulty,
            "url": self.url,
            "slug": self.slug
        }


class LeetCodeFetcher:
    """LeetCode 题目抓取器"""
    
    # LeetCode GraphQL API
    API_URL = "https://leetcode.com/graphql"
    CN_API_URL = "https://leetcode.cn/graphql"
    
    # 难度映射
    DIFFICULTY_MAP = {
        1: "Easy",
        2: "Medium", 
        3: "Hard"
    }
    
    def __init__(self, difficulties: List[str] = None):
        """
        初始化 LeetCode 抓取器
        
        Args:
            difficulties: 难度过滤列表 ["easy", "medium", "hard"]
        """
        self.difficulties = [d.lower() for d in (difficulties or [])]
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
    
    def _fetch_problem_list(self) -> List[Dict[str, Any]]:
        """
        获取题目列表
        
        Returns:
            题目列表
        """
        query = """
        query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
            problemsetQuestionList: questionList(
                categorySlug: $categorySlug
                limit: $limit
                skip: $skip
                filters: $filters
            ) {
                total: totalNum
                questions: data {
                    frontendQuestionId: questionFrontendId
                    title
                    titleCn: translatedTitle
                    titleSlug
                    difficulty
                    status
                    isPaidOnly
                }
            }
        }
        """
        
        variables = {
            "categorySlug": "",
            "skip": 0,
            "limit": 100,
            "filters": {}
        }
        
        try:
            # 尝试中国站点
            response = self.session.post(
                self.CN_API_URL,
                json={"query": query, "variables": variables},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                questions = data.get("data", {}).get("problemsetQuestionList", {}).get("questions", [])
                if questions:
                    return questions
            
            # 如果中国站点失败，尝试国际站点
            response = self.session.post(
                self.API_URL,
                json={"query": query, "variables": variables},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("data", {}).get("problemsetQuestionList", {}).get("questions", [])
                
        except Exception as e:
            logger.error(f"获取 LeetCode 题目列表失败: {e}")
        
        return []
    
    def _filter_problems(self, problems: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        过滤题目
        
        Args:
            problems: 原始题目列表
            
        Returns:
            过滤后的题目列表
        """
        filtered = []
        
        for problem in problems:
            # 跳过付费题目
            if problem.get("isPaidOnly"):
                continue
            
            # 难度过滤
            difficulty = problem.get("difficulty", "").lower()
            if self.difficulties and difficulty not in self.difficulties:
                continue
            
            filtered.append(problem)
        
        return filtered
    
    def get_random_problems(self, count: int = 2) -> List[LeetCodeProblem]:
        """
        获取随机题目
        
        Args:
            count: 题目数量
            
        Returns:
            题目列表
        """
        logger.info(f"正在从 LeetCode 获取 {count} 道随机题目...")
        
        problems = self._fetch_problem_list()
        if not problems:
            logger.warning("无法获取 LeetCode 题目列表，使用备用题目")
            return self._get_fallback_problems(count)
        
        # 过滤题目
        filtered = self._filter_problems(problems)
        if not filtered:
            logger.warning("过滤后无可用题目，使用原始列表")
            filtered = [p for p in problems if not p.get("isPaidOnly")]
        
        # 随机选择
        selected = random.sample(filtered, min(count, len(filtered)))
        
        result = []
        for problem in selected:
            slug = problem.get("titleSlug", "")
            result.append(LeetCodeProblem(
                title=problem.get("title", ""),
                title_cn=problem.get("titleCn", "") or problem.get("title", ""),
                difficulty=problem.get("difficulty", "Medium"),
                url=f"https://leetcode.cn/problems/{slug}/",
                slug=slug
            ))
        
        logger.info(f"成功获取 {len(result)} 道 LeetCode 题目")
        return result
    
    def _get_fallback_problems(self, count: int) -> List[LeetCodeProblem]:
        """
        备用题目列表（当 API 不可用时使用）
        
        Args:
            count: 题目数量
            
        Returns:
            题目列表
        """
        fallback = [
            LeetCodeProblem(
                title="Two Sum",
                title_cn="两数之和",
                difficulty="Easy",
                url="https://leetcode.cn/problems/two-sum/",
                slug="two-sum"
            ),
            LeetCodeProblem(
                title="Add Two Numbers",
                title_cn="两数相加",
                difficulty="Medium",
                url="https://leetcode.cn/problems/add-two-numbers/",
                slug="add-two-numbers"
            ),
            LeetCodeProblem(
                title="Longest Substring Without Repeating Characters",
                title_cn="无重复字符的最长子串",
                difficulty="Medium",
                url="https://leetcode.cn/problems/longest-substring-without-repeating-characters/",
                slug="longest-substring-without-repeating-characters"
            ),
            LeetCodeProblem(
                title="Valid Parentheses",
                title_cn="有效的括号",
                difficulty="Easy",
                url="https://leetcode.cn/problems/valid-parentheses/",
                slug="valid-parentheses"
            ),
            LeetCodeProblem(
                title="Merge Two Sorted Lists",
                title_cn="合并两个有序链表",
                difficulty="Easy",
                url="https://leetcode.cn/problems/merge-two-sorted-lists/",
                slug="merge-two-sorted-lists"
            ),
        ]
        
        return random.sample(fallback, min(count, len(fallback)))

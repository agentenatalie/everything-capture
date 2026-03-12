import datetime
import os
import sys
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Item  # noqa: E402
from routers.items import apply_platform_filter, rank_search_rows  # noqa: E402
from tenant import DEFAULT_USER_ID  # noqa: E402


class ProductSearchRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        now = datetime.datetime(2026, 3, 7, 12, 0, 0)
        self.rows = [
            SimpleNamespace(
                id="liquid-glass",
                title="眼馋苹果刚发布的液态玻璃效果？藏师傅教你提示词一键实现",
                canonical_text="苹果这次更新重点都放在视觉和交互上，Liquid Glass 的 UI 效果尤其出圈。",
                source_url="https://example.com/liquid-glass",
                platform="web",
                created_at=now - datetime.timedelta(hours=1),
            ),
            SimpleNamespace(
                id="component-library",
                title="担心 Vibe Coding 的审美？试试用组件库吧",
                canonical_text="shadcn/ui 可以降低审美落地成本，保证设计一致性，适合做 UI/UX 和视觉体验。",
                source_url="https://example.com/shadcn-ui",
                platform="xiaohongshu",
                created_at=now - datetime.timedelta(hours=2),
            ),
            SimpleNamespace(
                id="open-source-agent",
                title="十万人想要的社媒自动推送agent免费开源啦",
                canonical_text="这是一个免费开源 agent，可以自动监控内容并做信息推送。",
                source_url="https://example.com/social-agent",
                platform="xiaohongshu",
                created_at=now - datetime.timedelta(hours=3),
            ),
            SimpleNamespace(
                id="github-project",
                title="开源项目--1300 年前的唐朝制度，吊打了我用过的所有 AI 框架",
                canonical_text="项目地址 GitHub：https://github.com/cft0808/edict ，欢迎 Star。",
                source_url="https://github.com/cft0808/edict",
                platform="web",
                created_at=now - datetime.timedelta(hours=4),
            ),
            SimpleNamespace(
                id="life-growth",
                title="1.7亿阅读的“人生作弊码”，教你一天“重装你的人生系统”",
                canonical_text="关于个人成长、认知觉醒和思维成长的内容。",
                source_url="https://example.com/life-growth",
                platform="douyin",
                created_at=now - datetime.timedelta(hours=5),
            ),
        ]

    def test_uiux_query_ranks_design_related_results_first(self) -> None:
        ranked = rank_search_rows(self.rows, "uiux")

        self.assertEqual(ranked[0], "component-library")
        self.assertIn("liquid-glass", ranked[:3])
        self.assertNotIn("life-growth", ranked[:2])
        self.assertNotIn("github-project", ranked)

    def test_visual_effect_query_surfaces_liquid_glass(self) -> None:
        ranked = rank_search_rows(self.rows, "视觉效果")

        self.assertEqual(ranked[0], "liquid-glass")
        self.assertNotIn("component-library", ranked)

    def test_github_query_brings_open_source_items_to_the_top(self) -> None:
        ranked = rank_search_rows(self.rows, "github")

        self.assertEqual(ranked[0], "github-project")
        self.assertIn("open-source-agent", ranked[:2])
        self.assertNotIn("life-growth", ranked[:2])
        self.assertNotIn("component-library", ranked)


class PlatformFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_github_filter_matches_github_urls_and_excludes_web_bucket(self) -> None:
        with self.Session() as db:
            db.add_all(
                [
                    Item(
                        id="github-item",
                        user_id=DEFAULT_USER_ID,
                        source_url="https://github.com/octocat/hello-world",
                        final_url="https://github.com/octocat/hello-world",
                        title="GitHub - octocat/hello-world: example repo",
                        canonical_text="Example repository",
                        canonical_html="<p>Example repository</p>",
                        platform="generic",
                        status="ready",
                    ),
                    Item(
                        id="web-item",
                        user_id=DEFAULT_USER_ID,
                        source_url="https://example.com/article",
                        final_url="https://example.com/article",
                        title="Example article",
                        canonical_text="Example article",
                        canonical_html="<p>Example article</p>",
                        platform="generic",
                        status="ready",
                    ),
                ]
            )
            db.commit()

            github_ids = [item.id for item in apply_platform_filter(db.query(Item), "github").all()]
            web_ids = [item.id for item in apply_platform_filter(db.query(Item), "web").all()]

        self.assertEqual(github_ids, ["github-item"])
        self.assertEqual(web_ids, ["web-item"])


if __name__ == "__main__":
    unittest.main()

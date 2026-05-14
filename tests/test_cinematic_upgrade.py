import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from viralforge.caption_cleaner import caption_plan_for, clean_headline
from viralforge.depth_compositor import character_integration_for_scene, layers_for_scene
from viralforge.broll_engine import broll_for_scene
from viralforge.automation import choose_fresh_topic, recover_incomplete_render_packages
from viralforge.google_video_client import _extract_video_uri
from viralforge.google_video_adapter import _veo_prompt
from viralforge.growth import finalize_metadata
from viralforge.models import ResearchBundle, ResearchSource, Scene, ScenePlan, TrendItem, UploadMetadata, VideoPlan
from viralforge.nvidia_client import NvidiaProviderError, NvidiaUnifiedClient, _video_endpoint_for
from viralforge.nvidia_video_adapter import image_data_uri_from_frame
from viralforge.pexels_client import _best_video_file
from viralforge.pexels_client import PexelsClient, PexelsVideoCandidate
from viralforge.pexels_broll_adapter import _select_fresh_candidates
from viralforge.pexels_demo_renderer import (
    _ass_script,
    _caption_groups,
    _caption_timing,
    _queries_for_plan,
    _retime_scene_plans_to_voice,
    render_pexels_demo,
)
from viralforge.scene_quality_checker import score_scene_quality
from viralforge.shot_director import build_shot_sequence
from viralforge.scriptwriter import fallback_plan
from viralforge.secure_bot import ADMIN, GUEST, OWNER, VIEWER, SecureTelegramBot, split_command as secure_split_command
from viralforge.telegram_bot import TelegramController, _split_command
from viralforge.utils import read_json


def _scene(scene_id: str = "scene_01", headline: str = "AI worker needs guardrails") -> ScenePlan:
    scene = ScenePlan(
        scene_id=scene_id,
        start_time=0,
        end_time=6,
        purpose="warning",
        narration="Without guardrails, AI becomes expensive chaos.",
        headline_text=headline,
        visual_description="red-lit digital vault with permission gate",
        camera_motion="impact_shake",
        sfx=["bass_hit"],
        shot_types=["chaos_dashboard", "vault_access", "macro_ui"],
        location="red-lit digital vault",
        visual_metaphor={"theme": "risk", "objects": ["red warning light", "broken dashboard", "permission vault"]},
        foreground_elements=["red warning light", "permission vault"],
        character={"gesture": "step_forward", "expression": "serious"},
        vfx=["glitch", "red_flash", "particles", "warning_pulse"],
    )
    scene.shot_sequence = build_shot_sequence(
        scene_id=scene.scene_id,
        duration=scene.duration_seconds,
        purpose=scene.purpose,
        camera_emotion="danger",
        theme="risk",
        base_shots=scene.shot_types,
        scene_index=0,
    )
    scene.broll_clips = broll_for_scene(scene, scene.shot_sequence)
    scene.layers = layers_for_scene(scene)
    scene.caption_plan = caption_plan_for(scene)
    scene.character_integration = character_integration_for_scene(scene)
    scene.camera_emotion = "danger"
    return scene


class CinematicUpgradeTests(unittest.TestCase):
    def test_caption_cleaner_limits_broken_lines(self):
        headline, used_ellipsis = clean_headline(
            "AI interns: no...",
            "Your next intern will not sleep and will not ask for breaks.",
            "hook",
            ellipsis_allowed=False,
        )
        self.assertFalse(used_ellipsis)
        self.assertGreaterEqual(len(headline.split()), 3)
        self.assertLessEqual(len(headline.split()), 7)
        self.assertNotIn("...", headline)

    def test_broll_inserted_within_four_seconds(self):
        sequence = build_shot_sequence(
            scene_id="scene_01",
            duration=8.0,
            purpose="warning",
            camera_emotion="danger",
            theme="risk",
            base_shots=["hero_closeup"],
            scene_index=0,
        )
        change_starts = [
            float(shot["start"])
            for shot in sequence
            if shot["type"] in {"new_angle", "broll", "macro_ui", "character_closeup", "visual_metaphor"}
        ]
        points = [0.0, *change_starts, 8.0]
        self.assertTrue(any(shot["type"] == "broll" for shot in sequence))
        self.assertTrue(all(points[index + 1] - points[index] <= 4.05 for index in range(len(points) - 1)))

    def test_shot_director_scene_variety(self):
        sequence = build_shot_sequence(
            scene_id="scene_02",
            duration=6.5,
            purpose="control",
            camera_emotion="authority",
            theme="control",
            base_shots=["over_shoulder"],
            scene_index=1,
        )
        shot_names = {shot["shot"] for shot in sequence}
        change_types = {shot["type"] for shot in sequence}
        self.assertGreaterEqual(len(shot_names), 3)
        self.assertTrue({"broll", "macro_ui", "visual_metaphor"} & change_types)

    def test_quality_checker_rejects_repeated_template_scene(self):
        first = _scene("scene_01", "AI worker needs guardrails")
        second = _scene("scene_02", "AI worker needs guardrails")
        report = score_scene_quality(second, first)
        self.assertFalse(report["passed"])
        self.assertIn("Scene is too visually similar", " ".join(report["flags"]))

    def test_nvidia_video_path_is_image_to_video_not_chat(self):
        client = NvidiaUnifiedClient(SimpleNamespace())
        with self.assertRaises(NvidiaProviderError):
            client.generate_video("fake text-to-video prompt")
        self.assertEqual(
            _video_endpoint_for("stabilityai/stable-video-diffusion"),
            "/genai/stabilityai/stable-video-diffusion",
        )

    def test_nvidia_seed_frame_respects_inline_limit(self):
        frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
        frame[:, :, 0] = 8
        frame[420:1100, 220:860, 1] = 210
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.jpg"
            uri = image_data_uri_from_frame(frame, path)
            self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
            self.assertTrue(path.exists())
            self.assertLessEqual(path.stat().st_size, 198_000)

    def test_google_veo_uri_extraction_and_prompt_require_motion(self):
        scene = _scene()
        prompt = _veo_prompt(scene)
        self.assertIn("full-body movement", prompt)
        self.assertIn("Do not show readable on-screen text", prompt)
        uri = _extract_video_uri(
            {
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [{"video": {"uri": "https://example.com/video.mp4"}}]
                    }
                }
            }
        )
        self.assertEqual(uri, "https://example.com/video.mp4")

    def test_pexels_best_video_prefers_portrait_hd_mp4(self):
        chosen = _best_video_file(
            [
                {"file_type": "video/mp4", "width": 640, "height": 360, "quality": "sd", "link": "landscape"},
                {"file_type": "video/mp4", "width": 1080, "height": 1920, "quality": "hd", "link": "portrait"},
                {"file_type": "video/webm", "width": 1080, "height": 1920, "quality": "hd", "link": "webm"},
            ]
        )
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["link"], "portrait")

    def test_pexels_selection_avoids_recent_stock_ids(self):
        candidates = [
            PexelsVideoCandidate(
                id=index,
                url="",
                image="",
                duration=10,
                width=1080,
                height=1920,
                user_name="Pexels",
                user_url="",
                query="AI technology office" if index < 4 else "creator workspace",
                score=20 - index,
                download_url="",
                download_quality="hd",
                download_width=1080,
                download_height=1920,
            )
            for index in range(1, 8)
        ]
        selected = _select_fresh_candidates(candidates, {1, 2, 3}, 4)
        selected_ids = {candidate.id for candidate in selected}
        self.assertTrue({1, 2, 3}.isdisjoint(selected_ids))
        self.assertEqual(len(selected), 4)

    def test_pexels_selection_spreads_across_queries_before_reusing_one(self):
        candidates = [
            PexelsVideoCandidate(
                id=index,
                url="",
                image="",
                duration=10,
                width=1080,
                height=1920,
                user_name=f"Creator {index}",
                user_url="",
                query=query,
                score=20 - index,
                download_url="",
                download_quality="hd",
                download_width=1080,
                download_height=1920,
            )
            for index, query in enumerate(
                [
                    "AI technology office",
                    "AI technology office",
                    "video editor computer",
                    "podcast studio technology",
                    "business team laptop",
                ],
                start=1,
            )
        ]
        selected = _select_fresh_candidates(candidates, set(), 4)
        self.assertGreaterEqual(len({candidate.query for candidate in selected}), 4)

    def test_pexels_selection_prefers_different_creators(self):
        candidates = [
            PexelsVideoCandidate(
                id=index,
                url="",
                image="",
                duration=10,
                width=1080,
                height=1920,
                user_name=user,
                user_url="",
                query=query,
                score=20 - index,
                download_url="",
                download_quality="hd",
                download_width=1080,
                download_height=1920,
            )
            for index, (user, query) in enumerate(
                [
                    ("Same Creator", "creator workspace"),
                    ("Same Creator", "creator workspace"),
                    ("Different Creator A", "video editor computer"),
                    ("Different Creator B", "podcast studio technology"),
                ],
                start=1,
            )
        ]
        selected = _select_fresh_candidates(candidates, set(), 3)
        self.assertEqual(len({candidate.user_name for candidate in selected}), 3)

    def test_pexels_search_continues_after_query_timeout(self):
        class FakePexelsClient(PexelsClient):
            def search_videos(self, query, **kwargs):
                if query == "timeout":
                    raise TimeoutError("network stalled")
                return {
                    "total_results": 1,
                    "page": kwargs.get("page", 1),
                    "per_page": kwargs.get("per_page", 12),
                    "videos": [
                        {
                            "id": 42,
                            "url": "https://example.com/video",
                            "image": "",
                            "duration": 9,
                            "width": 1080,
                            "height": 1920,
                            "user": {"name": "Pexels", "url": "https://www.pexels.com/"},
                            "video_files": [
                                {
                                    "file_type": "video/mp4",
                                    "width": 1080,
                                    "height": 1920,
                                    "quality": "hd",
                                    "link": "https://example.com/video.mp4",
                                }
                            ],
                        }
                    ],
                }

        client = FakePexelsClient(SimpleNamespace(pexels_api_key="key"))
        selected, reports = client.collect_ranked_videos(["timeout", "working"], max_items=2)
        self.assertEqual([candidate.id for candidate in selected], [42])
        self.assertIn("error", reports[0])
        self.assertEqual(reports[1]["returned"], 1)

    def test_pexels_queries_are_topic_aware(self):
        creator_plan = VideoPlan(
            topic="creator economy AI tools",
            angle="Creators use AI to edit Shorts faster.",
            audience="creators",
            title="AI creator workflow",
            scenes=[Scene("AI edits creator videos.", "Creator Studio", "creator filming", 3)],
            metadata=UploadMetadata(title="", description="", hashtags=[], tags=[]),
        )
        science_plan = VideoPlan(
            topic="science technology breakthrough",
            angle="A lab discovers a new battery material.",
            audience="tech viewers",
            title="Science breakthrough",
            scenes=[Scene("A lab changes batteries.", "Lab Breakthrough", "science laboratory", 3)],
            metadata=UploadMetadata(title="", description="", hashtags=[], tags=[]),
        )
        self.assertNotEqual(_queries_for_plan(creator_plan)[:3], _queries_for_plan(science_plan)[:3])
        self.assertIn("content creator workspace", _queries_for_plan(creator_plan))
        self.assertIn("science laboratory technology", _queries_for_plan(science_plan))

    def test_pexels_renderer_rejects_underfilled_clip_pool(self):
        scenes = [_scene(f"scene_{index:02d}") for index in range(7)]
        for index, scene in enumerate(scenes):
            scene.start_time = index * 4
            scene.end_time = index * 4 + 4
        clips = [
            PexelsVideoCandidate(
                id=index,
                url="",
                image="",
                duration=10,
                width=1080,
                height=1920,
                user_name="Pexels",
                user_url="",
                query="video editor computer",
                score=10,
                download_url="",
                download_quality="hd",
                download_width=1080,
                download_height=1920,
                local_path=Path(f"clip_{index}.mp4"),
            )
            for index in range(6)
        ]
        plan = VideoPlan(
            topic="AI creator workflow",
            angle="Creators use AI tools.",
            audience="tech viewers",
            title="AI creator workflow",
            scenes=[Scene("Line", "Headline", "creator desk", 4) for _ in range(7)],
            metadata=UploadMetadata(title="", description="", hashtags=[], tags=[]),
        )
        settings = SimpleNamespace(pexels_max_clips=4, video_duration_seconds=24)
        with TemporaryDirectory() as tmp:
            with patch("viralforge.pexels_demo_renderer.create_scene_plan", return_value=scenes):
                with patch("viralforge.pexels_demo_renderer.prepare_pexels_broll", return_value=clips):
                    with self.assertRaisesRegex(RuntimeError, "avoid repeated footage"):
                        render_pexels_demo(plan, Path(tmp), settings)

    def test_pexels_captions_follow_voice_timeline(self):
        scene = _scene("scene_01")
        scene.start_time = 10
        scene.end_time = 16
        _retime_scene_plans_to_voice([scene], {"scene_01": (0.4, 2.1)})
        timings = _caption_timing(scene)
        self.assertLess(timings[0][0], 1.0)
        self.assertLessEqual(timings[-1][1], 2.4)
        ass = _ass_script([scene])
        self.assertIn("0:00:00.", ass)

    def test_pexels_ass_has_subscribe_and_no_source_banner(self):
        scene = _scene()
        ass = _ass_script([scene])
        self.assertIn("SUBSCRIBE FOR TECH", ass)
        self.assertNotIn("PEXELS COMMERCIAL", ass)
        self.assertNotIn("ORIGINAL AI SHORT", ass)
        self.assertIn("Kinetic", ass)

    def test_pexels_caption_groups_keep_readable_phrases(self):
        groups = _caption_groups(
            "Your next intern will not sleep. It will not ask for breaks. It will ask for access."
        )
        self.assertIn("WILL NOT SLEEP", groups)
        self.assertNotIn("NOT SLEEP NOT", groups)

    def test_metadata_adds_tech_format_hashtags(self):
        plan = VideoPlan(
            topic="AI quiz about new gadgets",
            angle="A fast tech quiz about AI gadgets.",
            audience="tech viewers",
            title="AI gadget quiz",
            scenes=[],
            metadata=UploadMetadata(title="AI gadget quiz", description="", hashtags=["#Shorts"], tags=[]),
        )
        bundle = ResearchBundle(
            topic="AI quiz about new gadgets",
            angle="A fast tech quiz about AI gadgets.",
            sources=[ResearchSource("New AI gadget quiz trend", "https://example.com", "test", "AI gadget quiz")],
        )
        settings = type(
            "Settings",
            (),
            {
                "youtube_category_id": "28",
                "youtube_privacy_status": "private",
                "youtube_contains_synthetic_media": False,
                "youtube_made_for_kids": False,
            },
        )()
        metadata = finalize_metadata(
            plan,
            bundle,
            settings,
            {"niches": ["AI tools"], "growth_strategy": {"max_hashtags": 8, "default_hashtags": ["#Tech"]}},
        )
        self.assertIn("#TechQuiz", metadata.hashtags)
        self.assertIn("#Gadgets", metadata.hashtags)

    def test_autopilot_skips_recent_duplicate_topic(self):
        trends = [
            TrendItem("AI gadget quiz trend", "https://example.com/1", "test", score=10),
            TrendItem("Cybersecurity news update", "https://example.com/2", "test", score=8),
        ]
        state = {"history": [{"topic": "AI gadget quiz trend"}]}
        self.assertEqual(choose_fresh_topic(trends, state), "Cybersecurity news update")

    def test_recover_incomplete_render_promotes_raw_video(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "20260513_010203_ai-test"
            output_dir.mkdir(parents=True)
            (output_dir / "video_raw.mp4").write_bytes(b"not a real mp4 but enough for fallback")
            (output_dir / "metadata.json").write_text(
                '{"title":"AI test","description":"","hashtags":["#Tech"],"tags":[]}',
                encoding="utf-8",
            )
            (output_dir / "plan.json").write_text('{"topic":"AI test"}', encoding="utf-8")
            settings = SimpleNamespace(outputs_dir=root, audio_target_lufs=-14, audio_sample_rate=48000)

            recovered = recover_incomplete_render_packages(settings)

            self.assertEqual(len(recovered), 1)
            self.assertTrue((output_dir / "video.mp4").exists())
            self.assertTrue((output_dir / "rendered.json").exists())
            state = read_json(root / "automation_state.json")
            self.assertEqual(state["history"][0]["video"], str(output_dir / "video.mp4"))

    def test_fallback_plan_matches_quiz_topic(self):
        settings = type(
            "Settings",
            (),
            {
                "video_duration_seconds": 34,
                "youtube_category_id": "28",
                "youtube_privacy_status": "private",
                "youtube_contains_synthetic_media": False,
                "youtube_made_for_kids": False,
            },
        )()
        bundle = ResearchBundle(
            topic="AI gadget quiz",
            angle="A fast tech quiz about AI gadgets.",
            sources=[],
        )
        plan = fallback_plan(settings, bundle, {"niches": ["AI tools"]})
        self.assertIn("Guess", plan.metadata.title)
        self.assertIn("quiz", " ".join(plan.metadata.tags).lower())
        self.assertNotIn("AI Agent", plan.metadata.title)

    def test_telegram_command_parsing(self):
        command, arg = _split_command("/run@viralforge_bot funny AI tools")
        self.assertEqual(command, "/run")
        self.assertEqual(arg, "funny AI tools")

    def test_telegram_requires_allowlist_for_commands(self):
        settings = type(
            "Settings",
            (),
            {
                "telegram_bot_token": "token",
                "telegram_allowed_chat_ids": [],
                "telegram_owner_chat_ids": [],
                "telegram_poll_timeout": 1,
                "telegram_send_video_max_mb": 45,
            },
        )()
        controller = TelegramController(settings, {})
        sent = []
        controller.send_message = lambda chat_id, text: sent.append((chat_id, text))
        controller.handle_update({"message": {"chat": {"id": 123}, "text": "/run AI news"}})
        self.assertIn("not allowed", sent[0][1])

    def test_secure_bot_roles_and_command_parser(self):
        with TemporaryDirectory() as tmp:
            settings = SimpleNamespace(
                telegram_bot_token="token",
                telegram_owner_chat_ids=[1],
                telegram_admin_chat_ids=[2],
                telegram_allowed_chat_ids=[3],
                telegram_poll_timeout=1,
                telegram_send_video_max_mb=45,
                secure_bot_max_daily_renders=6,
                secure_bot_max_daily_uploads=3,
                secure_bot_require_upload_approval=True,
                secure_bot_instance_lock_port=0,
                outputs_dir=Path(tmp),
                youtube_token_file=Path(tmp) / "youtube_token.json",
                youtube_client_secrets=Path(tmp) / "client_secret.json",
                youtube_privacy_status="private",
            )
            bot = SecureTelegramBot(settings, {})
            self.assertEqual(bot.role_for(1), OWNER)
            self.assertEqual(bot.role_for(2), ADMIN)
            self.assertEqual(bot.role_for(3), VIEWER)
            self.assertEqual(bot.role_for(4), GUEST)
            self.assertEqual(secure_split_command("/render_upload@vf_bot gadget quiz"), ("/render_upload", "gadget quiz"))

    def test_secure_bot_refuses_write_before_owner_claim(self):
        with TemporaryDirectory() as tmp:
            settings = SimpleNamespace(
                telegram_bot_token="token",
                telegram_owner_chat_ids=[],
                telegram_admin_chat_ids=[],
                telegram_allowed_chat_ids=[],
                telegram_poll_timeout=1,
                telegram_send_video_max_mb=45,
                secure_bot_max_daily_renders=6,
                secure_bot_max_daily_uploads=3,
                secure_bot_require_upload_approval=True,
                secure_bot_instance_lock_port=0,
                outputs_dir=Path(tmp),
                youtube_token_file=Path(tmp) / "youtube_token.json",
                youtube_client_secrets=Path(tmp) / "client_secret.json",
                youtube_privacy_status="private",
            )
            bot = SecureTelegramBot(settings, {})
            sent = []
            bot.send_message = lambda chat_id, text, reply_markup=None: sent.append((chat_id, text))
            bot.handle_update({"message": {"chat": {"id": 123}, "text": "/render AI news"}})
            self.assertIn("not claimed", sent[0][1])


if __name__ == "__main__":
    unittest.main()

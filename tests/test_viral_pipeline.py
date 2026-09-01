import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.create_viral_segments import (
    normalize_text,
    build_transcript_tokens,
    find_best_text_match,
    clamp_and_validate_duration,
    deduplicate_segments,
    create_transcript_chunks,
    process_segments,
    safe_score
)

class TestViralPipeline(unittest.TestCase):

    # ---------------------------------------------------------
    # 1. Normalization Tests
    # ---------------------------------------------------------
    def test_normalize_text_accents_and_punctuation(self):
        text = "  Olá, VOCÊ está aí?! Não perca essa oportunidade...  "
        normalized = normalize_text(text)
        self.assertEqual(normalized, "ola voce esta ai nao perca essa oportunidade")

    def test_normalize_text_empty_and_special(self):
        self.assertEqual(normalize_text(""), "")
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text("--- @#$% ---"), "")

    # ---------------------------------------------------------
    # 2. Chunking & Overlap Tests
    # ---------------------------------------------------------
    def test_chunking_single_chunk(self):
        content = "(0s) Este é um texto curto (5s) para teste de chunk único."
        chunks = create_transcript_chunks(content, chunk_size=500)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], content)

    def test_chunking_multi_chunk_overlap(self):
        # Generate longer text
        sentence = "Este é um trecho de transcrição para validar o fatiamento e overlap. "
        content = ""
        for i in range(20):
            content += f"({i*5}s) {sentence}"
        
        chunk_size = 200
        overlap_size = 50
        chunks = create_transcript_chunks(content, chunk_size=chunk_size, overlap_size=overlap_size)
        
        self.assertGreater(len(chunks), 1)
        for i, chunk in enumerate(chunks):
            self.assertLessEqual(len(chunk), chunk_size + 50)
            self.assertTrue(len(chunk) > 0)

    def test_chunking_tag_integrity(self):
        content = "(0s) Palavra1 palavra2 palavra3 (15s) palavra4 palavra5 (30s) palavra6"
        chunks = create_transcript_chunks(content, chunk_size=40, overlap_size=10)
        for chunk in chunks:
            # Verify no orphaned tag pieces like "(1" or "5s)"
            self.assertFalse(chunk.endswith("(1") or chunk.endswith("(3") or chunk.startswith("5s)"))

    # ---------------------------------------------------------
    # 3. Text Matching Tests
    # ---------------------------------------------------------
    def test_text_matching_accent_and_punctuation_tolerance(self):
        transcript = [
            {"start": 0.0, "end": 4.0, "text": "Olá a todos!"},
            {"start": 4.0, "end": 8.0, "text": "Hoje vamos falar de inteligência artificial."},
            {"start": 8.0, "end": 14.0, "text": "Não perca essa conclusão incrível."},
        ]
        tokens = build_transcript_tokens(transcript)

        # Query has no accents and different punctuation
        start_matched = find_best_text_match(
            target_text="hoje vamos falar de inteligencia artificial",
            tokens=tokens,
            transcript_segments=transcript,
            ref_time_val=4.0,
            is_end=False
        )
        self.assertAlmostEqual(start_matched, 4.0, delta=0.5)

        end_matched = find_best_text_match(
            target_text="nao perca essa conclusao incrivel",
            tokens=tokens,
            transcript_segments=transcript,
            ref_time_val=14.0,
            is_end=True
        )
        self.assertAlmostEqual(end_matched, 14.0, delta=0.5)

    def test_text_matching_multi_segment_span(self):
        transcript = [
            {"start": 10.0, "end": 12.0, "text": "O maior segredo"},
            {"start": 12.0, "end": 15.0, "text": "para ter sucesso"},
            {"start": 15.0, "end": 18.0, "text": "é a consistência diária."},
        ]
        tokens = build_transcript_tokens(transcript)

        # Target spans across segment 1 and 2
        start_matched = find_best_text_match(
            target_text="O maior segredo para ter sucesso",
            tokens=tokens,
            transcript_segments=transcript,
            ref_time_val=10.0,
            is_end=False
        )
        self.assertAlmostEqual(start_matched, 10.0, delta=0.2)

        # Target spans across segment 2 and 3
        end_matched = find_best_text_match(
            target_text="ter sucesso é a consistência diária",
            tokens=tokens,
            transcript_segments=transcript,
            ref_time_val=18.0,
            is_end=True
        )
        self.assertAlmostEqual(end_matched, 18.0, delta=0.2)

    def test_text_matching_fuzzy_typo(self):
        transcript = [
            {"start": 20.0, "end": 25.0, "text": "Este resultado surpreendeu toda a equipe técnica."}
        ]
        tokens = build_transcript_tokens(transcript)

        # Query has minor typo ("resultdo" instead of "resultado", "equipe tecnica")
        matched = find_best_text_match(
            target_text="Este resultdo surpreendeu toda equipe tecnica",
            tokens=tokens,
            transcript_segments=transcript,
            ref_time_val=20.0,
            is_end=False
        )
        self.assertAlmostEqual(matched, 20.0, delta=0.5)

    def test_text_matching_fallback_to_ref_time(self):
        transcript = [
            {"start": 0.0, "end": 10.0, "text": "Primeiro bloco"},
            {"start": 50.0, "end": 60.0, "text": "Segundo bloco"}
        ]
        tokens = build_transcript_tokens(transcript)

        # Target text completely absent
        matched = find_best_text_match(
            target_text="Texto inexistente que nao esta no video",
            tokens=tokens,
            transcript_segments=transcript,
            ref_time_val=52.0,
            is_end=False
        )
        self.assertAlmostEqual(matched, 50.0, delta=1.0)

    # ---------------------------------------------------------
    # 4. Duration & Boundary Clamping Tests
    # ---------------------------------------------------------
    def test_duration_extension_min_duration(self):
        # Clip is 5s, min_duration is 15s -> should extend to 15s
        start, end, dur = clamp_and_validate_duration(
            start_time=10.0, end_time=15.0, min_duration=15, max_duration=60, max_video_time=100.0
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 25.0)
        self.assertEqual(dur, 15.0)

    def test_duration_trimming_max_duration(self):
        # Clip is 80s, max_duration is 60s -> should trim to 60s
        start, end, dur = clamp_and_validate_duration(
            start_time=10.0, end_time=90.0, min_duration=15, max_duration=60, max_video_time=100.0
        )
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 70.0)
        self.assertEqual(dur, 60.0)

    def test_duration_clamping_video_boundary_edge(self):
        # Video is 100s long. Clip starts at 95s with min_duration=15s.
        # Should shift start back to 85s so end stays <= 100s and dur == 15s.
        start, end, dur = clamp_and_validate_duration(
            start_time=95.0, end_time=98.0, min_duration=15, max_duration=60, max_video_time=100.0
        )
        self.assertGreaterEqual(start, 0.0)
        self.assertLessEqual(end, 100.0)
        self.assertEqual(dur, 15.0)
        self.assertEqual(start, 85.0)
        self.assertEqual(end, 100.0)

    def test_duration_video_shorter_than_min_duration(self):
        # Video is only 10s total, min_duration is 15s -> returns full video [0.0, 10.0]
        start, end, dur = clamp_and_validate_duration(
            start_time=2.0, end_time=8.0, min_duration=15, max_duration=60, max_video_time=10.0
        )
        self.assertEqual(start, 0.0)
        self.assertEqual(end, 10.0)
        self.assertEqual(dur, 10.0)

    # ---------------------------------------------------------
    # 5. Deduplication & Score Prioritization Tests
    # ---------------------------------------------------------
    def test_deduplication_removes_overlapping_lower_score(self):
        segments = [
            {"title": "Low Score Clip", "start_time": 10.0, "end_time": 40.0, "score": 70, "duration": 30.0},
            {"title": "High Score Clip", "start_time": 12.0, "end_time": 42.0, "score": 95, "duration": 30.0},
            {"title": "Independent Clip", "start_time": 60.0, "end_time": 90.0, "score": 80, "duration": 30.0},
        ]
        unique = deduplicate_segments(segments, max_overlap_seconds=5.0, max_overlap_ratio=0.25)
        
        # Should keep "High Score Clip" and "Independent Clip", dropping "Low Score Clip"
        self.assertEqual(len(unique), 2)
        titles = [s["title"] for s in unique]
        self.assertIn("High Score Clip", titles)
        self.assertIn("Independent Clip", titles)
        self.assertNotIn("Low Score Clip", titles)

    def test_deduplication_keeps_non_overlapping_clips(self):
        segments = [
            {"title": "Clip 1", "start_time": 0.0, "end_time": 20.0, "score": 90, "duration": 20.0},
            {"title": "Clip 2", "start_time": 22.0, "end_time": 42.0, "score": 85, "duration": 20.0},
            {"title": "Clip 3", "start_time": 45.0, "end_time": 65.0, "score": 80, "duration": 20.0},
        ]
        unique = deduplicate_segments(segments)
        self.assertEqual(len(unique), 3)

    # ---------------------------------------------------------
    # 6. Global Top-N Selection Tests
    # ---------------------------------------------------------
    def test_process_segments_top_n_selection(self):
        transcript = [
            {"start": float(i * 10), "end": float((i + 1) * 10), "text": f"Texto do bloco {i}"}
            for i in range(20)
        ]
        raw_segments = [
            {"title": "Clip A", "start_text": "Texto do bloco 1", "end_text": "Texto do bloco 3", "score": 98, "start_time_ref": "(10s)"},
            {"title": "Clip B", "start_text": "Texto do bloco 5", "end_text": "Texto do bloco 7", "score": 95, "start_time_ref": "(50s)"},
            {"title": "Clip C", "start_text": "Texto do bloco 9", "end_text": "Texto do bloco 11", "score": 90, "start_time_ref": "(90s)"},
            {"title": "Clip D", "start_text": "Texto do bloco 13", "end_text": "Texto do bloco 15", "score": 80, "start_time_ref": "(130s)"},
        ]

        result = process_segments(
            raw_segments=raw_segments,
            transcript_segments=transcript,
            min_duration=15,
            max_duration=60,
            output_count=2
        )

        segments = result.get("segments", [])
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["title"], "Clip A")
        self.assertEqual(segments[1]["title"], "Clip B")
        self.assertEqual(segments[0]["score"], 98.0)
        self.assertEqual(segments[1]["score"], 95.0)

    # ---------------------------------------------------------
    # 7. Edge Cases & Robustness Tests
    # ---------------------------------------------------------
    def test_safe_score_formats(self):
        self.assertEqual(safe_score({"score": 95}), 95.0)
        self.assertEqual(safe_score({"score": "95"}), 95.0)
        self.assertEqual(safe_score({"score": "95.5%"}), 95.5)
        self.assertEqual(safe_score({"score": None}), 0.0)
        self.assertEqual(safe_score({}), 0.0)
        self.assertEqual(safe_score({"score": "invalid"}), 0.0)

    def test_process_segments_empty_inputs(self):
        self.assertEqual(process_segments([], [], 15, 60), {"segments": []})
        self.assertEqual(process_segments([{"title": "X"}], [], 15, 60), {"segments": []})
        self.assertEqual(process_segments([], [{"start": 0, "end": 10, "text": "A"}], 15, 60), {"segments": []})

    def test_cross_chunk_deduplication_and_global_top_n(self):
        # Simulates 2 chunks finding overlapping clips of the same moment with different scores
        transcript = [
            {"start": float(i * 5), "end": float((i + 1) * 5), "text": f"Segmento de fala número {i}"}
            for i in range(40) # 200 seconds video
        ]
        
        # Chunk 1 output + Chunk 2 output
        all_raw_from_chunks = [
            # Viral moment 1 (found in both chunk 1 and chunk 2)
            {"title": "Viral 1 (Chunk 1)", "start_text": "Segmento de fala número 2", "end_text": "Segmento de fala número 6", "score": 92, "start_time_ref": "(10s)"},
            {"title": "Viral 1 (Chunk 2)", "start_text": "Segmento de fala número 3", "end_text": "Segmento de fala número 7", "score": 97, "start_time_ref": "(15s)"},
            
            # Viral moment 2 (found in chunk 2)
            {"title": "Viral 2", "start_text": "Segmento de fala número 12", "end_text": "Segmento de fala número 16", "score": 88, "start_time_ref": "(60s)"},
            
            # Viral moment 3 (found in chunk 1)
            {"title": "Viral 3", "start_text": "Segmento de fala número 22", "end_text": "Segmento de fala número 26", "score": 85, "start_time_ref": "(110s)"},
        ]

        result = process_segments(
            raw_segments=all_raw_from_chunks,
            transcript_segments=transcript,
            min_duration=15,
            max_duration=60,
            output_count=2
        )

        segments = result.get("segments", [])
        self.assertEqual(len(segments), 2)
        # Viral 1 Chunk 2 (score 97) should win over Viral 1 Chunk 1 (score 92)
        self.assertEqual(segments[0]["title"], "Viral 1 (Chunk 2)")
        self.assertEqual(segments[0]["score"], 97.0)
        self.assertEqual(segments[1]["title"], "Viral 2")
        self.assertEqual(segments[1]["score"], 88.0)

if __name__ == '__main__':
    unittest.main()

from scripts import cut_json
import os
import subprocess
import json
from scripts.download_video import validate_video_file

# Global cache for encoder
CACHED_ENCODER = None

def get_best_encoder():
    global CACHED_ENCODER
    if CACHED_ENCODER:
        return CACHED_ENCODER
    
    try:
        result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
        output = result.stdout
        
        if "h264_nvenc" in output:
            CACHED_ENCODER = ("h264_nvenc", "p1")
            return CACHED_ENCODER
        if "h264_amf" in output:
            CACHED_ENCODER = ("h264_amf", "speed")
            return CACHED_ENCODER
        if "h264_qsv" in output:
            CACHED_ENCODER = ("h264_qsv", "veryfast")
            return CACHED_ENCODER
        if "h264_videotoolbox" in output:
            CACHED_ENCODER = ("h264_videotoolbox", "default")
            return CACHED_ENCODER
    except Exception as e:
        print(f"[WARN] Error checking ffmpeg encoders: {e}")

    CACHED_ENCODER = ("libx264", "ultrafast")
    return CACHED_ENCODER

def run_ffmpeg_cut(input_file, start_time_str, duration_str, output_path):
    """
    Executes FFmpeg cut with hardware encoder, automatic CPU fallback,
    returncode/stderr validation, and output container integrity check.
    """
    encoder_name, encoder_preset = get_best_encoder()

    def build_cmd(codec, preset):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-hide_banner",
            "-ss", start_time_str,
            "-i", input_file,
            "-t", duration_str,
            "-c:v", codec
        ]
        if "nvenc" in codec:
            cmd.extend(["-preset", "p1", "-b:v", "5M"])
        elif "amf" in codec:
            cmd.extend(["-preset", "speed", "-b:v", "5M"])
        elif "qsv" in codec:
            cmd.extend(["-preset", "veryfast", "-b:v", "5M"])
        else:
            cmd.extend(["-preset", "ultrafast", "-crf", "23"])

        cmd.extend([
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ])
        return cmd

    # 1. Tentativa com encoder preferencial
    try:
        cmd = build_cmd(encoder_name, encoder_preset)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        if validate_video_file(output_path):
            return True
    except (subprocess.CalledProcessError, Exception) as e:
        stderr_msg = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
        print(f"[WARN] FFmpeg cut failed with {encoder_name}: {stderr_msg}. Falling back to CPU libx264...")
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass

    # 2. Fallback CPU
    try:
        cmd_cpu = build_cmd("libx264", "ultrafast")
        subprocess.run(cmd_cpu, check=True, capture_output=True, text=True)
        if validate_video_file(output_path):
            return True
        else:
            raise RuntimeError(f"Output cut file {output_path} is invalid after CPU cut.")
    except subprocess.CalledProcessError as e2:
        stderr_msg2 = e2.stderr if hasattr(e2, 'stderr') and e2.stderr else str(e2)
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        raise RuntimeError(f"FFmpeg error cutting segment to {output_path}: {stderr_msg2}") from e2

def cut(segments, project_folder="tmp", skip_video=False):
    # Procurar input_video.mp4 no project_folder ou tmp
    input_file = os.path.join(project_folder, "input.mp4")
    if not os.path.exists(input_file):
        input_file_legacy = os.path.join(project_folder, "input_video.mp4")
        if os.path.exists(input_file_legacy):
            input_file = input_file_legacy
        else:
            print(f"Input file not found in {project_folder}")
            return

    # Pasta de saida para os cortes
    cuts_folder = os.path.join(project_folder, "cuts")
    os.makedirs(cuts_folder, exist_ok=True)
    
    # Pasta de saida para legendas json cortadas
    subs_folder = os.path.join(project_folder, "subs")
    os.makedirs(subs_folder, exist_ok=True)

    # Input JSON (Transcrição original)
    input_json_path = os.path.join(project_folder, "input.json")

    # Reading the JSON file if segments not provided
    if segments is None:
        json_path = os.path.join(project_folder, 'viral_segments.txt')
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as file:
                response = json.load(file)
        else:
            print(f"Viral segments file not found: {json_path}")
            return
    else:
        response = segments

    segment_list = response.get("segments", [])
    for i, segment in enumerate(segment_list):
        start_time = segment.get("start_time", 0.0)
        duration = segment.get("duration", 0.0)

        # Normalização de duration
        if isinstance(duration, (int, float)):
            if duration < 1000:
                duration_seconds = float(duration)
            else:
                duration_seconds = duration / 1000.0
            duration_str = f"{duration_seconds:.3f}"
        else:
            try:
                duration_seconds = float(duration)
                duration_str = f"{duration_seconds:.3f}"
            except ValueError:
                duration_seconds = 0.0
                duration_str = str(duration)
        
        # Normalização de start_time
        if isinstance(start_time, (int, float)):
            start_time_seconds = float(start_time)
            start_time_str = f"{start_time_seconds:.3f}"
        else:
            try:
                start_time_seconds = float(start_time)
                start_time_str = f"{start_time_seconds:.3f}"
            except Exception:
                try:
                    parts = str(start_time).split(':')
                    if len(parts) == 3:
                        start_time_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    elif len(parts) == 2:
                        start_time_seconds = int(parts[0]) * 60 + float(parts[1])
                    else:
                        start_time_seconds = float(parts[0])
                    start_time_str = f"{start_time_seconds:.3f}"
                except Exception:
                    start_time_seconds = 0.0
                    start_time_str = "0.000"

        # Título para nome de arquivo com sanitização segura
        title = segment.get("title", f"Segment_{i}")
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"]).strip()
        safe_title = safe_title.replace(" ", "_")[:60]
        if not safe_title:
            safe_title = f"Segment_{i}"
        base_name = f"{i:03d}_{safe_title}"

        output_filename = f"{base_name}_original_scale.mp4"
        output_path = os.path.join(cuts_folder, output_filename)

        print(f"Processing segment {i+1}/{len(segment_list)}")
        print(f"Start time: {start_time_str}s, Duration: {duration_str}s")

        # VIDEO GENERATION COM IDEMPOTÊNCIA POR SEGMENTO
        segment_already_valid = validate_video_file(output_path)
        if skip_video or segment_already_valid:
            if segment_already_valid:
                file_size = os.path.getsize(output_path)
                print(f"Reusing existing valid segment: {output_filename}, Size: {file_size} bytes")
            else:
                print(f"Skipping video generation for {output_filename} (skip_video requested).")
        else:
            run_ffmpeg_cut(input_file, start_time_str, duration_str, output_path)
            file_size = os.path.getsize(output_path)
            print(f"Generated segment: {output_filename}, Size: {file_size} bytes")
        
        # --- JSON CUTTING (ALWAYS RUN TO ENSURE UP-TO-DATE SUBS) ---
        end_time_seconds = start_time_seconds + float(duration_seconds)
        json_output_filename = f"{base_name}_processed.json"
        json_output_path = os.path.join(subs_folder, json_output_filename)
        
        cut_json.cut_json_transcript(input_json_path, json_output_path, start_time_seconds, end_time_seconds)
        print("\n" + "="*50 + "\n")

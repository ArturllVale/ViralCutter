import os
import subprocess
import sys
from scripts.download_video import validate_video_file
from scripts.cut_segments import get_best_encoder

def escape_ffmpeg_filter_path(file_path):
    """
    Escapes a filesystem path for safe use inside FFmpeg filtergraphs on Windows and POSIX.
    Handles drive letter colons, forward slashes, and quotes.
    """
    abs_p = os.path.abspath(file_path).replace('\\', '/')
    abs_p = abs_p.replace(':', r'\:')
    abs_p = abs_p.replace("'", r"\'")
    return abs_p

def burn_video_file(video_path, subtitle_path, output_path):
    """
    Burns subtitles into a single video file with hardware encoder fallback,
    returncode/stderr validation, and container integrity verification.
    """
    if validate_video_file(output_path):
        return True, "Already exists and valid"

    subtitle_file_ffmpeg = escape_ffmpeg_filter_path(subtitle_path)
    encoder_name, encoder_preset = get_best_encoder()

    def run_ffmpeg(encoder, preset, additional_args=[]):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error", "-hide_banner",
            '-i', video_path,
            '-vf', f"subtitles='{subtitle_file_ffmpeg}'",
            '-c:v', encoder,
            '-preset', preset,
            '-b:v', '5M',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'copy',
            output_path
        ] + additional_args
        return subprocess.run(cmd, check=True, capture_output=True, text=True)

    # 1. Tentativa com encoder detectado
    try:
        run_ffmpeg(encoder_name, encoder_preset)
        if validate_video_file(output_path):
            return True, f"{encoder_name} Success"
        else:
            if os.path.exists(output_path):
                try: os.remove(output_path)
                except Exception: pass
            raise RuntimeError(f"Output file {output_path} is corrupt or empty after {encoder_name} burn.")
    except (subprocess.CalledProcessError, Exception) as e:
        stderr_msg = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
        print(f"[WARN] Hardware subtitle burning failed with {encoder_name}: {stderr_msg}. Retrying with CPU libx264...")
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except Exception: pass

    # 2. Fallback CPU
    try:
        run_ffmpeg("libx264", "ultrafast")
        if validate_video_file(output_path):
            return True, "CPU Success"
        else:
            if os.path.exists(output_path):
                try: os.remove(output_path)
                except Exception: pass
            return False, f"Output file {output_path} is corrupt after CPU burn."
    except subprocess.CalledProcessError as e2:
        stderr_msg2 = e2.stderr if hasattr(e2, 'stderr') and e2.stderr else str(e2)
        err_msg = f"ERRO FATAL ao queimar legendas em {os.path.basename(video_path)}: {stderr_msg2}"
        print(err_msg)
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except Exception: pass
        return False, err_msg
    except Exception as e3:
        if os.path.exists(output_path):
            try: os.remove(output_path)
            except Exception: pass
        return False, str(e3)

def burn(project_folder="tmp"):
    if project_folder and not os.path.isabs(project_folder):
        project_folder_abs = os.path.abspath(project_folder)
    else:
        project_folder_abs = project_folder

    subs_folder = os.path.join(project_folder_abs, 'subs_ass')
    videos_folder = os.path.join(project_folder_abs, 'final')
    output_folder = os.path.join(project_folder_abs, 'burned_sub')

    os.makedirs(output_folder, exist_ok=True)
    
    if not os.path.exists(videos_folder):
        print(f"Pasta de vídeos finais não encontrada: {videos_folder}")
        return

    files = os.listdir(videos_folder)
    if not files:
        print("Nenhum arquivo encontrado em 'final' para queimar legendas.")
        return

    for video_file in files:
        if video_file.endswith(('.mp4', '.mkv', '.avi')):
            if "temp_video_no_audio" in video_file:
                continue

            video_name = os.path.splitext(video_file)[0]
            subtitle_file = os.path.join(subs_folder, f"{video_name}.ass")
            
            if not os.path.exists(subtitle_file):
                subtitle_file_processed = os.path.join(subs_folder, f"{video_name}_processed.ass")
                if os.path.exists(subtitle_file_processed):
                    subtitle_file = subtitle_file_processed
            
            if os.path.exists(subtitle_file):
                output_file = os.path.join(output_folder, f"{video_name}_subtitled.mp4")

                # Idempotência: verificar se já existe e é válido
                if validate_video_file(output_file):
                    print(f"Reusing existing subtitled video: {output_file}")
                    continue

                print(f"Burning: {video_name}...")
                success, msg = burn_video_file(os.path.join(videos_folder, video_file), subtitle_file, output_file)
                if success:
                    print(f"Done: {output_file}")
                else:
                    print(f"Fail: {msg}")
            else:
                print(f"Legenda não encontrada para: {video_name} em {subtitle_file}")

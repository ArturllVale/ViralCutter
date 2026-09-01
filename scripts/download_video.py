import os
import re
import sys
import json
import time
import glob
from enum import Enum
import yt_dlp
from i18n.i18n import I18nAuto

i18n = I18nAuto()

class DownloadErrorCategory(Enum):
    INVALID_URL = "invalid_url"
    UNAVAILABLE_OR_PRIVATE = "unavailable_or_private"
    AUTHENTICATION_REQUIRED = "authentication_required"
    ANTI_BOT = "anti_bot"
    RATE_LIMIT = "rate_limit"
    NETWORK_TRANSIENT = "network_transient"
    UNKNOWN = "unknown"

def sanitize_log_message(msg):
    """
    Strips cookies, authorization tokens, passwords, and sensitive query params from logs.
    """
    if not isinstance(msg, str):
        msg = str(msg)
    # Mask cookies and auth tokens
    msg = re.sub(r'(cookie[s]?:?\s*)[^\s,]+', r'\1***REDACTED***', msg, flags=re.IGNORECASE)
    msg = re.sub(r'(bearer\s+)[^\s,]+', r'\1***REDACTED***', msg, flags=re.IGNORECASE)
    msg = re.sub(r'(password[=:]\s*)[^\s,]+', r'\1***REDACTED***', msg, flags=re.IGNORECASE)
    msg = re.sub(r'(key[=:]\s*)[^\s,]+', r'\1***REDACTED***', msg, flags=re.IGNORECASE)
    msg = re.sub(r'([?&](?:token|session_id|auth|signature|sig)=)[^&\s]+', r'\1***REDACTED***', msg, flags=re.IGNORECASE)
    return msg

def classify_ytdlp_error(error):
    """
    Classifies a yt-dlp error into a DownloadErrorCategory and indicates if it is transient (retryable).
    Returns (category, is_transient, user_friendly_message).
    """
    msg = str(error).lower()
    
    # 1. Invalid URL
    if "is not a valid url" in msg or "unsupported url" in msg or "invalid url" in msg:
        return (
            DownloadErrorCategory.INVALID_URL,
            False,
            "URL inválida ou não suportada."
        )

    # 2. Unavailable, Private, Deleted, Geo-blocked
    if (
        "private video" in msg
        or "video unavailable" in msg
        or "this video has been removed" in msg
        or "not available in your country" in msg
        or "geoblocked" in msg
        or "copyright" in msg
        or "members-only" in msg
        or "this video is unavailable" in msg
        or "has been terminated" in msg
    ):
        return (
            DownloadErrorCategory.UNAVAILABLE_OR_PRIVATE,
            False,
            "Vídeo privado, indisponível, removido ou bloqueado geograficamente."
        )

    # 3. Anti-bot / Captcha
    if (
        "sign in to confirm you're not a bot" in msg
        or "confirm you're not a bot" in msg
        or "bot detection" in msg
        or "captcha" in msg
    ):
        return (
            DownloadErrorCategory.ANTI_BOT,
            False,
            "Bloqueio anti-bot do YouTube detectado. Configure cookies válidos (--cookies-from-browser ou --cookiefile)."
        )

    if (
        "sign in to view" in msg
        or "login required" in msg
        or "requires authentication" in msg
    ):
        return (
            DownloadErrorCategory.AUTHENTICATION_REQUIRED,
            False,
            "Autenticação necessária para acessar este vídeo. Forneça cookies de autenticação."
        )

    # 4. Rate limit (HTTP 429)
    if "429" in msg or "too many requests" in msg or "rate limit" in msg:
        return (
            DownloadErrorCategory.RATE_LIMIT,
            True,
            "Rate limit (HTTP 429 / Too Many Requests) atingido no YouTube."
        )

    # 5. Network / Transient errors
    if (
        "no address associated with hostname" in msg
        or "failed to resolve" in msg
        or "temporary failure" in msg
        or "connection reset" in msg
        or "remotedisconnected" in msg
        or "timed out" in msg
        or "timeout" in msg
        or "http error 500" in msg
        or "http error 502" in msg
        or "http error 503" in msg
        or "http error 504" in msg
        or "incompleteread" in msg
        or "socket" in msg
        or "network is unreachable" in msg
        or "eof occurred" in msg
        or "ssl" in msg
    ):
        return (
            DownloadErrorCategory.NETWORK_TRANSIENT,
            True,
            "Falha transitória de rede ou servidor."
        )

    return (
        DownloadErrorCategory.UNKNOWN,
        False,
        "Erro desconhecido durante o download."
    )

def sanitize_filename(name):
    """Remove caracteres inválidos e emojis para evitar erro de encoding no Windows."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    try:
        cleaned = cleaned.encode('cp1252', 'ignore').decode('cp1252')
    except Exception:
        cleaned = cleaned.encode('ascii', 'ignore').decode('ascii')
    return cleaned.strip()

def progress_hook(d):
    if d.get('status') == 'downloading':
        try:
            p = d.get('_percent_str', '').replace('%', '')
            print(f"[download] {p}% - {d.get('_eta_str', 'N/A')} remaining", flush=True)
        except Exception:
            pass
    elif d.get('status') == 'finished':
        filename = sanitize_log_message(d.get('filename', ''))
        print(f"[download] Download concluído: {filename}", flush=True)

def resolve_cookie_config(cookies_from_browser=None, cookiefile=None, config_path=None):
    """
    Resolves cookie configuration from explicit arguments, environment variables, or api_config.json.
    Returns (cookies_from_browser, cookiefile) tuple.
    """
    if cookies_from_browser:
        return (str(cookies_from_browser).strip().lower(), None)
    if cookiefile:
        return (None, str(cookiefile).strip())

    env_browser = os.environ.get("VIRALCUTTER_COOKIES_FROM_BROWSER") or os.environ.get("YTDLP_COOKIES_FROM_BROWSER")
    if env_browser:
        return (env_browser.strip().lower(), None)
    env_file = os.environ.get("VIRALCUTTER_COOKIEFILE") or os.environ.get("YTDLP_COOKIEFILE")
    if env_file:
        return (None, env_file.strip())

    if not config_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'api_config.json')

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                ytdlp_cfg = cfg.get("ytdlp", {})
                if ytdlp_cfg.get("cookies_from_browser"):
                    return (str(ytdlp_cfg["cookies_from_browser"]).strip().lower(), None)
                if ytdlp_cfg.get("cookiefile"):
                    return (None, str(ytdlp_cfg["cookiefile"]).strip())
        except Exception:
            pass

    return (None, None)

def build_ydl_options(
    output_path_base,
    selected_format="bestvideo+bestaudio/best",
    download_subs=True,
    cookies_from_browser=None,
    cookiefile=None,
    quiet=False,
    include_progress=True
):
    opts = {
        'format': selected_format,
        'overwrites': True,
        'outtmpl': output_path_base,
        'postprocessor_args': ['-movflags', 'faststart'],
        'merge_output_format': 'mp4',
        'writesubtitles': download_subs,
        'writeautomaticsub': download_subs,
        'subtitleslangs': ['pt.*', 'en.*', 'sp.*', 'es.*'],
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        },
        'skip_download': False,
        'quiet': quiet,
        'no_warnings': quiet,
        'force_ipv4': True,
    }

    if include_progress:
        opts['progress_hooks'] = [progress_hook]

    if cookies_from_browser:
        opts['cookiesfrombrowser'] = (cookies_from_browser,)
    elif cookiefile:
        opts['cookiefile'] = cookiefile

    if download_subs:
        opts['postprocessors'] = [{
            'key': 'FFmpegSubtitlesConvertor',
            'format': 'srt',
        }]

    return opts

def validate_video_file(file_path, min_size_bytes=10240):
    """
    Verifies that file_path exists, is non-empty, and has a recognizable video container signature.
    """
    if not file_path or not os.path.exists(file_path):
        return False

    try:
        size = os.path.getsize(file_path)
        if size < min_size_bytes:
            return False

        with open(file_path, 'rb') as f:
            header = f.read(64)
            # MP4 (ftyp/moov) or Matroska/WebM (EBML 0x1A45DFA3)
            if b'ftyp' in header or b'moov' in header or b'\x1a\x45\xdf\xa3' in header:
                return True
        return True
    except Exception:
        return False

def cleanup_corrupted_or_temp_files(output_path_base):
    """Removes lingering .temp, .part, .ytdl, or temporary download artifacts."""
    folder = os.path.dirname(output_path_base)
    base_name = os.path.basename(output_path_base)
    
    if not os.path.exists(folder):
        return

    for fname in os.listdir(folder):
        if fname.startswith(base_name):
            full_p = os.path.join(folder, fname)
            if fname.endswith(('.part', '.temp', '.ytdl', '.tmp', '.temp.mp4')):
                try:
                    os.remove(full_p)
                except Exception:
                    pass

def convert_vtt_to_srt(project_folder):
    """
    Finds downloaded VTT subtitles, converts karaoke/roll-up VTT to standard clean SRT,
    and standardizes filename to input.srt.
    """
    try:
        potential_subs = glob.glob(os.path.join(project_folder, "input.*.vtt")) + glob.glob(os.path.join(project_folder, "input.*.srt"))
        if not potential_subs:
            return

        best_sub = potential_subs[0]
        ext = os.path.splitext(best_sub)[1]
        new_name = os.path.join(project_folder, "input.srt")

        if ext.lower() == '.vtt':
            try:
                print(i18n("Formatting complex VTT subtitle ({}) to clean SRT...").format(os.path.basename(best_sub)))
            except UnicodeEncodeError:
                print("Formatting complex VTT subtitle to clean SRT...")

            try:
                with open(best_sub, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                srt_content = []
                counter = 1
                last_text = ""
                current_start = ""
                current_end = ""

                for line in lines:
                    clean_line = line.strip()
                    if (
                        clean_line.startswith("WEBVTT")
                        or clean_line.startswith("X-TIMESTAMP")
                        or clean_line.startswith("NOTE")
                        or clean_line.startswith("Kind:")
                        or clean_line.startswith("Language:")
                    ):
                        continue

                    if "-->" in clean_line:
                        parts = clean_line.split("-->")
                        start = parts[0].strip()
                        end = parts[1].strip().split(' ')[0]

                        def fix_time(t):
                            t = t.strip().split()[0]
                            if '.' in t:
                                hms, ms = t.split('.', 1)
                                ms = (ms + "000")[:3]
                            elif ',' in t:
                                hms, ms = t.split(',', 1)
                                ms = (ms + "000")[:3]
                            else:
                                hms, ms = t, "000"
                            parts = hms.split(':')
                            try:
                                if len(parts) == 3:
                                    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
                                elif len(parts) == 2:
                                    h, m, s = 0, int(parts[0]), int(parts[1])
                                elif len(parts) == 1:
                                    h, m, s = 0, 0, int(parts[0])
                                else:
                                    h, m, s = 0, 0, 0
                                return f"{h:02d}:{m:02d}:{s:02d},{ms}"
                            except ValueError:
                                return "00:00:00,000"

                        current_start = fix_time(start)
                        current_end = fix_time(end)
                    elif clean_line:
                        text = re.sub(r'<[^>]+>', '', clean_line).strip()
                        if not text:
                            continue

                        lines_in_text = text.split('\n')
                        final_line = lines_in_text[-1].strip()
                        if not final_line or final_line == last_text:
                            continue

                        if current_start and current_end:
                            srt_content.append(f"{counter}\n")
                            srt_content.append(f"{current_start} --> {current_end}\n")
                            srt_content.append(f"{final_line}\n\n")

                            last_text = final_line
                            counter += 1

                with open(new_name, 'w', encoding='utf-8') as f_out:
                    f_out.writelines(srt_content)

                try:
                    os.remove(best_sub)
                except Exception:
                    pass

            except Exception as e_conv:
                print(i18n("Failed to convert VTT: {}. Keeping original.").format(sanitize_log_message(str(e_conv))))
                new_name_fallback = os.path.join(project_folder, "input.vtt")
                if os.path.exists(new_name_fallback) and new_name_fallback != best_sub:
                    try:
                        os.remove(new_name_fallback)
                    except Exception:
                        pass
                os.rename(best_sub, new_name_fallback)
        else:
            if os.path.exists(new_name) and new_name != best_sub:
                try:
                    os.remove(new_name)
                except Exception:
                    pass
            os.rename(best_sub, new_name)

        # Cleanup extra sub files
        for extra in potential_subs[1:]:
            try:
                os.remove(extra)
            except Exception:
                pass

    except Exception as e_ren:
        print(i18n("Error processing subtitles: {}").format(sanitize_log_message(str(e_ren))))


def download(
    url,
    base_root="VIRALS",
    download_subs=True,
    quality="best",
    cookies_from_browser=None,
    cookiefile=None,
    max_retries=3
):
    """
    Downloads YouTube video and subtitles with configurable cookies, retry logic for transient errors,
    and container validation.
    """
    # Resolve cookies configuration
    resolved_browser, resolved_cookiefile = resolve_cookie_config(
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile
    )

    if resolved_browser:
        print(i18n("Using cookies from browser: {}").format(resolved_browser))
    elif resolved_cookiefile:
        print(i18n("Using cookie file: {}").format(resolved_cookiefile))

    # 1. Extrair informações do vídeo para pegar o título (com retry seletivo)
    print(i18n("Extracting video information..."))
    title = None
    info_opts = build_ydl_options(
        output_path_base="",
        download_subs=False,
        cookies_from_browser=resolved_browser,
        cookiefile=resolved_cookiefile,
        quiet=True,
        include_progress=False
    )
    info_opts['extract_flat'] = False

    for attempt in range(1, max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and isinstance(info, dict):
                    title = info.get('title')
                    break
        except Exception as e:
            category, is_transient, friendly_msg = classify_ytdlp_error(e)
            sanitized_err = sanitize_log_message(str(e))
            print(f"[WARN] {friendly_msg} ({category.value}): {sanitized_err}")

            if not is_transient or attempt == max_retries:
                # Fatal error or exhausted retries
                if category in (DownloadErrorCategory.INVALID_URL, DownloadErrorCategory.UNAVAILABLE_OR_PRIVATE, DownloadErrorCategory.ANTI_BOT, DownloadErrorCategory.AUTHENTICATION_REQUIRED):
                    raise RuntimeError(f"{friendly_msg} Detalhes: {sanitized_err}") from e
                break

            wait_time = 2 ** attempt
            print(f"[INFO] Tentando novamente extrair informações em {wait_time}s... (Tentativa {attempt+1}/{max_retries})")
            time.sleep(wait_time)

    if title:
        safe_title = sanitize_filename(title)
        try:
            print(i18n("Detected title: {}").format(title))
        except UnicodeEncodeError:
            clean_title = title.encode('ascii', 'replace').decode('ascii')
            print(i18n("Detected title: {}").format(clean_title))
    else:
        print(i18n("WARNING: Title could not be obtained. Using 'Unknown_Video'."))
        safe_title = i18n("Unknown_Video")

    # 2. Criar estrutura de pastas
    project_folder = os.path.join(base_root, safe_title)
    os.makedirs(project_folder, exist_ok=True)

    output_filename = 'input'
    output_path_base = os.path.join(project_folder, output_filename)
    final_video_path = f"{output_path_base}.mp4"

    # Verificação de arquivo local existente e válido
    if os.path.exists(final_video_path):
        if validate_video_file(final_video_path):
            try:
                print(i18n("Video already exists at: {}").format(final_video_path))
            except UnicodeEncodeError:
                print(i18n("Video already exists at: {}").format(final_video_path.encode('ascii', 'replace').decode('ascii')))
            print(i18n("Skipping download and reusing local file."))
            return final_video_path, project_folder
        else:
            print(i18n("Existing file found but seems corrupted/empty. Downloading again..."))
            try:
                os.remove(final_video_path)
            except Exception:
                pass

    cleanup_corrupted_or_temp_files(output_path_base)

    # Mapeamento de Qualidade
    quality_map = {
        "best": 'bestvideo+bestaudio/best',
        "1080p": 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
        "720p": 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        "480p": 'bestvideo[height<=480]+bestaudio/best[height<=480]'
    }
    selected_format = quality_map.get(quality, 'bestvideo+bestaudio/best')
    print(i18n("Configuring download quality: {} -> {}").format(quality, selected_format))

    # 3. Download do Vídeo
    try:
        print(i18n("Downloading video to: {}...").format(project_folder))
    except UnicodeEncodeError:
        print(i18n("Downloading video to: {}...").format(project_folder.encode('ascii', 'replace').decode('ascii')))

    current_download_subs = download_subs

    for attempt in range(1, max_retries + 1):
        ydl_opts = build_ydl_options(
            output_path_base=output_path_base,
            selected_format=selected_format,
            download_subs=current_download_subs,
            cookies_from_browser=resolved_browser,
            cookiefile=resolved_cookiefile,
            quiet=False,
            include_progress=True
        )

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Check if file was created and is valid
            if validate_video_file(final_video_path):
                break
            else:
                # Check if file was downloaded with another extension (e.g. .mkv / .webm) and merged
                candidates = glob.glob(f"{output_path_base}.*")
                video_candidates = [c for c in candidates if c.endswith(('.mp4', '.mkv', '.webm')) and not c.endswith(('.part', '.temp.mp4'))]
                if video_candidates and validate_video_file(video_candidates[0]):
                    if video_candidates[0] != final_video_path:
                        os.rename(video_candidates[0], final_video_path)
                    break
                raise RuntimeError("Arquivo de vídeo baixado é inválido ou corrompido.")

        except Exception as e:
            category, is_transient, friendly_msg = classify_ytdlp_error(e)
            sanitized_err = sanitize_log_message(str(e))
            error_str = str(e)

            # Subtitle error fallback
            if current_download_subs and ("Unable to download video subtitles" in error_str or "subtitles" in error_str.lower() or "429" in error_str):
                print(i18n("\nWarning: Error downloading subtitles ({}).").format(friendly_msg))
                print(i18n("Retrying ONLY the video (without subtitles)..."))
                current_download_subs = False
                continue

            print(f"[ERROR] {friendly_msg} ({category.value}): {sanitized_err}")

            if not is_transient or attempt == max_retries:
                cleanup_corrupted_or_temp_files(output_path_base)
                raise RuntimeError(f"Erro fatal no download: {friendly_msg} ({sanitized_err})") from e

            wait_time = 2 ** attempt
            print(f"[INFO] Aguardando {wait_time}s antes de tentar novamente o download... (Tentativa {attempt+1}/{max_retries})")
            time.sleep(wait_time)

    # Validação pós-download final
    if not validate_video_file(final_video_path):
        cleanup_corrupted_or_temp_files(output_path_base)
        raise RuntimeError("Download finalizado mas o arquivo de vídeo não é válido ou está corrompido.")

    # 4. Formatar/Converter Legendas
    if current_download_subs:
        convert_vtt_to_srt(project_folder)

    return final_video_path, project_folder
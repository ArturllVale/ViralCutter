import json
import os
import re
import sys
import time
import ast
import io
import unicodedata
import difflib

# Configura stdout para evitar erros de encoding no Windows (substitui caracteres inválidos por ?)
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    try:
        # Mantém encoding original mas ignora erros (substitui por ?)
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding=sys.stdout.encoding or 'utf-8', errors='replace', line_buffering=True)
    except:
        pass

# Tenta importar bibliotecas de IA opcionalmente
try:
    import google.genai as genai
    from google.genai.errors import APIError
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    import g4f
    HAS_G4F = True
except ImportError:
    HAS_G4F = False

try:
    from llama_cpp import Llama
    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False

def clean_json_response(response_text):
    """
    Limpa a resposta focando em encontrar o objeto JSON que contém a chave "segments".
    Estratégia:
    1. Busca a palavra "segments", encontra o '{' anterior e usa raw_decode.
    2. Fallback: Parsear lista de segmentos item a item (recuperação de JSON truncado).
    """
    if not isinstance(response_text, str):
        response_text = str(response_text)

    if not response_text:
        return {"segments": []}

    # 1. Limpeza preliminar
    # Remove tags de pensamento (DeepSeek R1)
    response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)

    # Normaliza escapes excessivos (\n virando \\n) e aspas se parecer necessário
    try:
        if "\\n" in response_text or "\\\"" in response_text:
             # Tenta um decode básico de escapes
             response_text = response_text.replace("\\n", "\n").replace("\\\"", "\"").replace("\\'", "'")
    except:
        pass

    # 2. Busca pela palavra-chave "segments"
    # Procura índices de todas as ocorrências de 'segments'
    matches = [m.start() for m in re.finditer(r'segments', response_text)]

    if not matches:
        # Se não achou segments, retorna vazio
        return {"segments": []}

    # Tenta extrair JSON válido a partir de cada ocorrência
    for match_idx in matches:
        # Procura o '{' mais próximo ANTES de "segments"
        # Limita busca a 5000 chars para trás para performance
        start_search = max(0, match_idx - 5000)
        snippet_before = response_text[start_search:match_idx]

        # Encontra o ÚLTIMO '{' no snippet
        last_open_rel = snippet_before.rfind('{')

        if last_open_rel != -1:
            real_start = start_search + last_open_rel
            candidate_text = response_text[real_start:]

            # Tentativa A: json.raw_decode
            try:
                decoder = json.JSONDecoder()
                obj, _ = decoder.raw_decode(candidate_text)
                if 'segments' in obj and isinstance(obj['segments'], list):
                    return obj
            except:
                pass

            # Tentativa B: ast.literal_eval
            try:
                balance = 0
                in_string = False
                escape = False
                found_end = -1

                for i, char in enumerate(candidate_text):
                    if escape:
                        escape = False
                        continue
                    if char == '\\':
                        escape = True
                        continue
                    if char == "'" or char == '"':
                        in_string = not in_string
                        continue

                    if not in_string:
                        if char == '{':
                            balance += 1
                        elif char == '}':
                            balance -= 1
                            if balance == 0:
                                found_end = i
                                break

                if found_end != -1:
                    clean_cand = candidate_text[:found_end+1]
                    obj = ast.literal_eval(clean_cand)
                    if 'segments' in obj and isinstance(obj['segments'], list):
                        return obj
            except:
                pass

    # 3. Fallback: Extração bruta de markdown
    try:
        match = re.search(r"```json(.*?)```", response_text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    except:
        pass

    # 4. LAST RESORT: Fragment Parser (Para JSON truncado/incompleto)
    # Procura por "segments": [ e tenta parsear item por item
    try:
        match_list = re.search(r'"segments"\s*:\s*\[', response_text)
        if match_list:
            start_pos = match_list.end()
            current_pos = start_pos
            found_segments = []
            decoder = json.JSONDecoder()

            while True:
                while current_pos < len(response_text) and response_text[current_pos] in ' \t\n\r,':
                    current_pos += 1

                if current_pos >= len(response_text):
                    break

                if response_text[current_pos] == ']':
                    break

                try:
                    obj, end_pos = decoder.raw_decode(response_text[current_pos:])
                    if isinstance(obj, dict):
                        found_segments.append(obj)
                    current_pos += end_pos
                except json.JSONDecodeError:
                    break

            if found_segments:
                print(f"[INFO] Recuperado {len(found_segments)} segmentos de JSON truncado.")
                return {"segments": found_segments}
    except:
        pass

    return {"segments": []}


def preprocess_transcript_for_ai(segments):
    """
    Concatenates transcript segments into a single string with embedded time tags.
    """
    if not segments:
        return ""

    full_text = ""
    last_tag_time = -100  # Force first tag

    # Try to start with (0s) based on first segment
    first_start = segments[0].get('start', 0)
    full_text += f"({int(first_start)}s) "
    last_tag_time = first_start

    for seg in segments:
        text = seg.get('text', '').strip()
        end_time = seg.get('end', 0)

        full_text += text + " "

        if end_time - last_tag_time >= 4:
            full_text += f"({int(end_time)}s) "
            last_tag_time = end_time

    return full_text.strip()

def call_gemini(prompt, api_key, model_name='gemini-2.5-flash'):
    if not HAS_GEMINI:
        raise ImportError("A biblioteca 'google-genai' não está instalada. Instale com: pip install google-genai")

    client = genai.Client(api_key=api_key)

    # Validação do modelo com fallback
    try:
        client.models.get(model=model_name)
    except APIError as e:
        code = e.code if hasattr(e, 'code') else None
        msg = str(e.message) if hasattr(e, 'message') and e.message else str(e)
        if code == 404 or "not found" in msg.lower() or "invalid model" in msg.lower():
            print(f"Erro: Modelo Gemini '{model_name}' inválido ou descontinuado. Usando fallback para 'gemini-2.5-flash'.")
            model_name = 'gemini-2.5-flash'
        elif code == 400 or "api key" in msg.lower():
            raise ValueError("Erro: Chave de API Gemini inválida.")
        else:
            # Check if it was an invalid model fallback we missed
            if "not found" in msg.lower() or code == 404:
                model_name = 'gemini-2.5-flash'
            else:
                print(f"Aviso ao validar o modelo {model_name}: {msg}")
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower() or "invalid" in msg.lower():
             model_name = 'gemini-2.5-flash'
        else:
             print(f"Aviso ao validar o modelo {model_name}: {e}")

    max_retries = 5
    base_wait = 30

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            return response.text
        except APIError as e:
            code = e.code if hasattr(e, 'code') else None
            msg = str(e.message) if hasattr(e, 'message') and e.message else str(e)
            if code == 429 or "quota" in msg.lower() or "too many requests" in msg.lower():
                wait_time = base_wait * (attempt + 1)

                match = re.search(r"retry in (\d+(\.\d+)?)s", msg.lower())
                if match:
                    wait_time = float(match.group(1)) + 5

                print(f"Rate limit do Gemini atingido. Aguardando {wait_time}s... (Tentativa {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            elif code == 404:
                print(f"Erro na API do Gemini: Modelo {model_name} não encontrado no generate_content. Falhando.")
                raise ValueError(f"Modelo inválido: {model_name}")
            else:
                print(f"Erro na API do Gemini: {msg}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(5)
        except Exception as e:
            print(f"Erro na API do Gemini: {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(5)
    print("Falha após max retries no Gemini.")
    return ""

def call_g4f(prompt, model_name="gpt-4o-mini"):
    if not HAS_G4F:
        raise ImportError("A biblioteca 'g4f' não está instalada. Instale com: pip install g4f")

    max_retries = 3
    base_wait = 5

    for attempt in range(max_retries):
        try:
            response = g4f.ChatCompletion.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
            )

            if isinstance(response, dict):
                if 'error' in response:
                    raise Exception(f"API Error: {response['error']}")
                if 'choices' in response and isinstance(response['choices'], list):
                    if len(response['choices']) > 0:
                         content = response['choices'][0].get('message', {}).get('content', '')
                         if content:
                             return content
                if not response:
                     raise ValueError("Empty Dict response")

                return json.dumps(response)

            if not response:
                print(f"[WARN] G4F retornou resposta vazia. Tentativa {attempt+1}/{max_retries}")
                time.sleep(base_wait)
                continue

            if isinstance(response, str):
                return response

            try:
                return json.dumps(response, ensure_ascii=False)
            except:
                return str(response)

        except Exception as e:
            print(f"[WARN] Erro na API do G4F (Tentativa {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = base_wait * (2 ** attempt)
                time.sleep(wait_time)

    print(f"Falha crítica após {max_retries} tentativas no G4F.")
    return "{}"

def load_transcript(project_folder):
    """Parses input.tsv or input.srt from the project folder."""
    input_tsv = os.path.join(project_folder, 'input.tsv')
    input_srt = os.path.join(project_folder, 'input.srt')

    transcript_segments = []

    # Try to load TSV first (more reliable time)
    if os.path.exists(input_tsv):
        try:
            with open(input_tsv, 'r', encoding='utf-8') as f:
                # Skip header
                lines = f.readlines()[1:]
                for line in lines:
                    parts = line.strip().split('\t')
                    if len(parts) >= 3:
                        start_ms = float(parts[0])
                        end_ms = float(parts[1])
                        text = parts[2]
                        transcript_segments.append({
                            'start': start_ms / 1000.0,
                            'end': end_ms / 1000.0,
                            'text': text
                        })
        except Exception as e:
            print(f"Error parsing TSV: {e}")

    # Fallback to SRT parser if TSV empty/failed
    if not transcript_segments and os.path.exists(input_srt):
         with open(input_srt, 'r', encoding='utf-8') as f:
             srt_content = f.read()
         pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n((?:(?!\n\n).)*)', re.DOTALL)
         matches = pattern.findall(srt_content)

         def srt_time_to_seconds(t_str):
             h, m, s = t_str.replace(',', '.').split(':')
             return int(h) * 3600 + int(m) * 60 + float(s)

         for m in matches:
             start_sec = srt_time_to_seconds(m[1])
             end_sec = srt_time_to_seconds(m[2])
             text = m[3].replace('\n', ' ')
             transcript_segments.append({'start': start_sec, 'end': end_sec, 'text': text})

    if not transcript_segments:
        raise ValueError("Could not parse transcript from TSV or SRT.")

    return transcript_segments

def normalize_text(text):
    """
    Normalizes text by:
    - Lowercasing
    - Decomposing unicode and stripping diacritics / accents (NFKD)
    - Removing all punctuation and non-alphanumeric characters
    - Collapsing multiple whitespace characters into a single space
    """
    if not text:
        return ""
    text = str(text).lower()
    nfkd = unicodedata.normalize('NFKD', text)
    without_accents = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    clean = re.sub(r'[^\w\s]', ' ', without_accents)
    return ' '.join(clean.split())

def build_transcript_tokens(transcript_segments):
    """
    Builds a flattened list of normalized word tokens with interpolated timestamps
    and segment references for fast, robust sequence matching.
    """
    tokens = []
    for seg_idx, seg in enumerate(transcript_segments):
        seg_text = seg.get('text', '')
        seg_start = float(seg.get('start', 0.0))
        seg_end = float(seg.get('end', seg_start))
        
        norm = normalize_text(seg_text)
        words = norm.split()
        if not words:
            continue
        
        n_words = len(words)
        dur = max(0.0, seg_end - seg_start)
        step = dur / n_words if n_words > 0 else 0.0
        
        for w_idx, w in enumerate(words):
            w_start = seg_start + w_idx * step
            w_end = seg_start + (w_idx + 1) * step if w_idx < n_words - 1 else seg_end
            tokens.append({
                'word': w,
                'seg_idx': seg_idx,
                'start': w_start,
                'end': w_end
            })
    return tokens

def find_best_text_match(target_text, tokens, transcript_segments, ref_time_val, is_end=False, min_start_time=0.0, max_search_time=None):
    """
    Finds the best matching timestamp in the transcript for target_text.
    Tolerates accent variations, punctuation, minor word omissions, and multi-segment spans.
    """
    norm_target = normalize_text(target_text)
    t_words = norm_target.split()
    
    if not tokens:
        if transcript_segments:
            if is_end:
                return float(transcript_segments[-1].get('end', ref_time_val))
            return float(transcript_segments[0].get('start', ref_time_val))
        return float(ref_time_val)

    if not t_words:
        # Fallback if no target text provided
        return float(ref_time_val)

    k = len(t_words)
    target_str = ' '.join(t_words)

    # Filter candidate token indices by time range if specified
    valid_indices = []
    for idx, tok in enumerate(tokens):
        if tok['start'] < min_start_time - 1.0:
            continue
        if max_search_time is not None and tok['start'] > max_search_time:
            break
        valid_indices.append(idx)

    if not valid_indices:
        valid_indices = list(range(len(tokens)))

    best_score = -1.0
    best_match_span = None

    # Try variable window lengths around k to accommodate missing/extra words (e.g. k-2 to k+2)
    min_window = max(1, k - 2)
    max_window = k + 3

    for start_i in valid_indices:
        for w_len in range(min_window, max_window + 1):
            end_i = min(len(tokens), start_i + w_len)
            window_tokens = tokens[start_i:end_i]
            if not window_tokens:
                continue
                
            window_words = [t['word'] for t in window_tokens]
            
            # Exact token match shortcut
            if window_words == t_words:
                similarity = 1.0
            else:
                window_str = ' '.join(window_words)
                similarity = difflib.SequenceMatcher(None, target_str, window_str).ratio()

            if similarity < 0.4:
                continue

            tok_time = window_tokens[0]['start'] if not is_end else window_tokens[-1]['end']
            time_diff = abs(tok_time - ref_time_val)
            combined_score = similarity - (time_diff * 0.0005)
            
            if combined_score > best_score:
                best_score = combined_score
                best_match_span = (start_i, end_i)
                if similarity == 1.0 and time_diff < 5.0:
                    break

    if best_match_span is not None and best_score >= 0.35:
        start_i, end_i = best_match_span
        if is_end:
            return tokens[end_i - 1]['end']
        return tokens[start_i]['start']

    # Fallback to closest segment to ref_time_val
    closest_seg = min(transcript_segments, key=lambda s: abs(float(s.get('start', 0.0)) - float(ref_time_val)))
    return float(closest_seg.get('end' if is_end else 'start', ref_time_val))

def clamp_and_validate_duration(start_time, end_time, min_duration, max_duration, max_video_time):
    """
    Ensures start_time >= 0.0, end_time <= max_video_time, and duration is within [min_duration, max_duration].
    Adjusts boundaries dynamically when close to video edges.
    """
    start = max(0.0, float(start_time))
    end = float(end_time)
    
    if max_video_time is not None and max_video_time > 0:
        max_limit = float(max_video_time)
    else:
        max_limit = max(end, float(max_duration))

    end = min(max_limit, end)

    if end <= start:
        end = min(max_limit, start + float(min_duration))

    duration = end - start

    if max_limit < float(min_duration):
        start = 0.0
        end = max_limit
    else:
        if duration < float(min_duration):
            end = min(max_limit, start + float(min_duration))
            if (end - start) < float(min_duration):
                start = max(0.0, end - float(min_duration))
        elif duration > float(max_duration):
            end = start + float(max_duration)

    final_dur = max(0.0, end - start)
    return round(start, 3), round(end, 3), round(final_dur, 3)

def safe_score(seg):
    """Safely extracts a numeric score from segment dictionary."""
    val = seg.get('score', 0)
    if isinstance(val, (int, float)):
        return float(val)
    try:
        clean = re.sub(r'[^\d.]', '', str(val))
        return float(clean) if clean else 0.0
    except:
        return 0.0

def deduplicate_segments(segments, max_overlap_seconds=5.0, max_overlap_ratio=0.25):
    """
    Deduplicates candidate segments based on score and time overlap (IoU and intersection ratio).
    Segments with higher scores take precedence.
    """
    if not segments:
        return []

    sorted_segs = sorted(
        segments,
        key=lambda x: (safe_score(x), float(x.get('duration', 0))),
        reverse=True
    )

    unique = []
    for candidate in sorted_segs:
        c_start = float(candidate.get('start_time', 0))
        c_end = float(candidate.get('end_time', 0))
        c_dur = max(0.001, c_end - c_start)

        is_dup = False
        for existing in unique:
            e_start = float(existing.get('start_time', 0))
            e_end = float(existing.get('end_time', 0))
            e_dur = max(0.001, e_end - e_start)

            overlap_start = max(c_start, e_start)
            overlap_end = min(c_end, e_end)

            if overlap_end > overlap_start:
                intersection = overlap_end - overlap_start
                union = max(c_end, e_end) - min(c_start, e_start)
                iou = intersection / union if union > 0 else 0.0
                ratio = intersection / min(c_dur, e_dur)

                if intersection > max_overlap_seconds or iou > max_overlap_ratio or ratio > 0.35:
                    is_dup = True
                    print(f"[DEBUG] Dropping overlap: '{candidate.get('title')}' ({c_start:.1f}-{c_end:.1f}s) overlaps with '{existing.get('title')}' ({e_start:.1f}-{e_end:.1f}s) [Intersection: {intersection:.1f}s, IoU: {iou:.2f}]")
                    break

        if not is_dup:
            unique.append(candidate)

    return unique

def create_transcript_chunks(content, chunk_size=15000, overlap_size=None):
    """
    Chunks a text transcript containing (XXs) tags into overlapping segments of approximately chunk_size.
    Ensures:
    - Never splits time tags like (123s).
    - Splits on word boundaries.
    - Preserves overlap between consecutive chunks.
    - Strictly monotonic progress.
    """
    if not content:
        return []
        
    content_len = len(content)
    chunk_size = int(chunk_size)
    if content_len <= chunk_size:
        return [content]

    if overlap_size is None:
        overlap_size = max(500, int(chunk_size * 0.1))
    else:
        overlap_size = int(overlap_size)
        
    overlap_size = max(50, min(overlap_size, int(chunk_size * 0.4)))

    chunks = []
    start = 0

    while start < content_len:
        end = min(start + chunk_size, content_len)
        
        if end < content_len:
            # Avoid cutting in middle of a tag like "(123s)"
            tag_match = re.search(r'\(\d+s?\)?$', content[start:end])
            if tag_match:
                end = start + tag_match.start()
            
            last_space = content.rfind(' ', start, end)
            if last_space != -1 and last_space > start + (chunk_size // 3):
                end = last_space

        chunk_text = content[start:end].strip()
        if chunk_text:
            chunks.append(chunk_text)

        if end >= content_len:
            break

        # Calculate next start with overlap
        target_start = max(start + 1, end - overlap_size)
        next_space = content.find(' ', target_start, min(target_start + 100, content_len))
        if next_space != -1 and next_space < end:
            start = next_space + 1
        else:
            start = target_start

    return chunks

def process_segments(raw_segments, transcript_segments, min_duration, max_duration, output_count=None):
    """
    Aligns raw AI segments (with reference tags and start/end text) to actual transcript timestamps.
    Applies text matching (tolerant to accents, punctuation, typos), duration constraints,
    video boundary clamping, score-based deduplication, and global top-N selection.
    """
    if not raw_segments or not transcript_segments:
        return {"segments": []}

    tempo_minimo = float(min_duration)
    tempo_maximo = float(max_duration)
    max_video_time = max((float(s.get('end', 0.0)) for s in transcript_segments), default=0.0)

    # Build token list for fast, fuzzy multi-word alignment
    tokens = build_transcript_tokens(transcript_segments)

    processed_segments = []
    print(f"[DEBUG] Matching {len(raw_segments)} raw segments to transcript timestamps...")

    for seg in raw_segments:
        try:
            # 1. Parse Reference Time
            ref_time_str = seg.get('start_time_ref', '(0s)')
            ref_time_val = 0.0
            try:
                if isinstance(ref_time_str, (int, float)):
                    ref_time_val = float(ref_time_str)
                elif isinstance(ref_time_str, str):
                    m = re.search(r'\d+', ref_time_str)
                    if m:
                        ref_time_val = float(m.group())
            except:
                ref_time_val = 0.0

            # 2. Match Start Text
            start_text = seg.get('start_text', '')
            final_start_time = find_best_text_match(
                target_text=start_text,
                tokens=tokens,
                transcript_segments=transcript_segments,
                ref_time_val=ref_time_val,
                is_end=False
            )

            # 3. Match End Text
            end_text = seg.get('end_text', '')
            min_end_search = final_start_time + (tempo_minimo * 0.4)
            max_end_search = final_start_time + (tempo_maximo * 1.5)
            
            final_end_time = find_best_text_match(
                target_text=end_text,
                tokens=tokens,
                transcript_segments=transcript_segments,
                ref_time_val=final_start_time + tempo_minimo,
                is_end=True,
                min_start_time=min_end_search,
                max_search_time=max_end_search
            )

            # 4. Validate & Clamp Duration within Video Limits
            start_clamped, end_clamped, duration_clamped = clamp_and_validate_duration(
                start_time=final_start_time,
                end_time=final_end_time,
                min_duration=tempo_minimo,
                max_duration=tempo_maximo,
                max_video_time=max_video_time
            )

            score_val = safe_score(seg)

            processed_segments.append({
                "title": seg.get('title', 'Viral Segment'),
                "start_time": start_clamped,
                "end_time": end_clamped,
                "hook": seg.get('hook', seg.get('title', '')),
                "reasoning": seg.get('reasoning', ''),
                "score": score_val,
                "duration": duration_clamped
            })

        except Exception as e:
            print(f"[WARN] Error processing segment {seg}: {e}")
            continue

    # 5. Deduplication across all chunks
    unique_segments = deduplicate_segments(processed_segments)
    print(f"[DEBUG] Finished processing. {len(unique_segments)} segments valid after deduplication.")

    # 6. Global Top-N Selection
    if output_count is not None:
        try:
            count_limit = int(output_count)
            if count_limit > 0 and len(unique_segments) > count_limit:
                print(f"Filtrando os top {count_limit} segmentos de {len(unique_segments)} candidatos encontrados.")
                unique_segments = unique_segments[:count_limit]
        except (ValueError, TypeError):
            pass

    return {"segments": unique_segments}


def create(num_segments, viral_mode, themes, tempo_minimo, tempo_maximo, ai_mode="manual", api_key=None, project_folder="tmp", chunk_size_arg=None, model_name_arg=None):
    quantidade_de_virals = num_segments

    # 1. Load Transcript
    transcript_segments = load_transcript(project_folder)

    # 2. Pre-process Content
    formatted_content = preprocess_transcript_for_ai(transcript_segments)
    content = formatted_content

    # Load Config and Prompt
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, 'api_config.json')
    prompt_path = os.path.join(base_dir, 'prompt.txt')

    config = {
        "selected_api": "gemini",
        "gemini": {
            "api_key": "",
            "model": "gemini-2.5-flash",
            "chunk_size": 15000
        },
        "g4f": {
            "model": "gpt-4o-mini",
            "chunk_size": 2000
        }
    }

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                loaded_config = json.load(f)
                if "gemini" in loaded_config: config["gemini"].update(loaded_config["gemini"])
                if "g4f" in loaded_config: config["g4f"].update(loaded_config["g4f"])
                if "selected_api" in loaded_config: config["selected_api"] = loaded_config["selected_api"]
        except Exception as e:
            print(f"Erro ao ler api_config.json: {e}")

    # Config Vars
    current_chunk_size = 15000
    model_name = ""

    if ai_mode == "gemini":
        cfg_chunk = config["gemini"].get("chunk_size", 15000)
        current_chunk_size = chunk_size_arg if chunk_size_arg and int(chunk_size_arg) > 0 else cfg_chunk
        cfg_model = config["gemini"].get("model", "gemini-2.5-flash")
        model_name = model_name_arg if model_name_arg else cfg_model
        if not api_key: api_key = config["gemini"].get("api_key", "")

    elif ai_mode == "g4f":
        cfg_chunk = config["g4f"].get("chunk_size", 2000)
        current_chunk_size = chunk_size_arg if chunk_size_arg and int(chunk_size_arg) > 0 else cfg_chunk
        cfg_model = config["g4f"].get("model", "gpt-4o-mini")
        model_name = model_name_arg if model_name_arg else cfg_model

    elif ai_mode == "local":
        current_chunk_size = chunk_size_arg if chunk_size_arg and int(chunk_size_arg) > 0 else 3000
        model_name = model_name_arg if model_name_arg else ""

    system_prompt_template = ""
    if os.path.exists(prompt_path):
        with open(prompt_path, 'r', encoding='utf-8') as f:
            system_prompt_template = f.read()
    else:
        print("Aviso: prompt.txt não encontrado. Usando prompt interno.")
        system_prompt_template = """You are a World-Class Viral Video Editor.
{context_instruction}
Analyze the transcript below with time tags (XXs). Find {amount} viral segments.
Constraints: Each segment MUST be between {min_duration} seconds and {max_duration} seconds.
IMPORTANT: Output "Title", "Hook", and "Reasoning" in the SAME LANGUAGE as the transcript (e.g., if transcript is Portuguese, output Portuguese).
TRANSCRIPT:
{transcript_chunk}
OUTPUT JSON ONLY:
{json_template}"""


    json_template = '''
            { "segments" :
                [
                    {
                        "start_text": "Exact first 5-10 words of the segment",
                        "end_text": "Exact last 5-10 words of the segment",
                        "start_time_ref": "Value of closest (XXs) tag",
                        "title": "Viral Hook Title (Same Language as Transcript)",
                        "reasoning": "Why this is viral? Hook? Value? (Same Language as Transcript)",
                        "score": 95
                    }
                ]
            }
        '''

    # Chunking
    chunk_size = int(current_chunk_size)
    overlap_size = max(1000, int(chunk_size * 0.1))
    chunks = create_transcript_chunks(content, chunk_size=chunk_size, overlap_size=overlap_size)
    print(f"[DEBUG] Chunking content (Size: {len(content)}) into {len(chunks)} chunks with Chunk Size: {chunk_size} and Overlap: {overlap_size}")

    if viral_mode:
        virality_instruction = f"""analyze the segment for potential virality and identify {quantidade_de_virals} most viral segments from the transcript"""
    else:
        virality_instruction = f"""analyze the segment for potential virality and identify {quantidade_de_virals} the best parts based on the list of themes {themes}."""

    output_texts = []
    for i, chunk in enumerate(chunks):
        context_instruction = ""
        if len(chunks) > 1:
            context_instruction = f"Part {i+1} of {len(chunks)}. "

        try:
            prompt = system_prompt_template.format(
                context_instruction=context_instruction,
                virality_instruction=virality_instruction,
                min_duration=tempo_minimo,
                max_duration=tempo_maximo,
                transcript_chunk=chunk,
                json_template=json_template,
                amount=quantidade_de_virals
            )
        except KeyError as e:
            prompt = system_prompt_template
            prompt = prompt.replace("{context_instruction}", context_instruction)
            prompt = prompt.replace("{virality_instruction}", virality_instruction)
            prompt = prompt.replace("{min_duration}", str(tempo_minimo))
            prompt = prompt.replace("{max_duration}", str(tempo_maximo))
            prompt = prompt.replace("{transcript_chunk}", chunk)
            prompt = prompt.replace("{json_template}", json_template)
            prompt = prompt.replace("{amount}", str(quantidade_de_virals))

        output_texts.append(prompt)

    try:
        full_prompt_path = os.path.join(project_folder, "prompt_full.txt")
        full_prompt = system_prompt_template
        full_prompt = full_prompt.replace("{context_instruction}", "Full Video Transcript Analysis")
        full_prompt = full_prompt.replace("{virality_instruction}", virality_instruction)
        full_prompt = full_prompt.replace("{min_duration}", str(tempo_minimo))
        full_prompt = full_prompt.replace("{max_duration}", str(tempo_maximo))
        full_prompt = full_prompt.replace("{transcript_chunk}", content)
        full_prompt = full_prompt.replace("{json_template}", json_template)
        full_prompt = full_prompt.replace("{amount}", str(quantidade_de_virals))

        with open(full_prompt_path, "w", encoding="utf-8") as f:
            f.write(full_prompt)
    except Exception as e:
        print(f"[WARN] Could not save prompt_full.txt: {e}")

    all_raw_segments = []

    print(f"Processando {len(output_texts)} chunks usando modo: {ai_mode.upper()}")

    local_llm_instance = None
    if ai_mode == "local":
        if not HAS_LLAMA_CPP:
            print("Error: llama-cpp-python not installed. Please install it to use Local mode.")
            return {"segments": []}

        models_dir = os.path.join(base_dir, 'models')
        model_path = os.path.join(models_dir, model_name)
        if not os.path.exists(model_path):
             if os.path.exists(model_name):
                 model_path = model_name
             else:
                 print(f"Error: Model not found at {model_path}")
                 return {"segments": []}

        print(f"[INFO] Loading Local Model: {os.path.basename(model_path)} (This may take a while)...")
        try:
            local_llm_instance = Llama(
                model_path=model_path,
                n_gpu_layers=-1,
                n_ctx=8192,
                verbose=False
            )
        except Exception as e:
            print(f"Failed to load model: {e}")
            return {"segments": []}

    for i, prompt in enumerate(output_texts):
        response_text = ""
        manual_prompt_path = os.path.join(project_folder, f"prompt_part_{i+1}.txt")
        try:
            with open(manual_prompt_path, "w", encoding="utf-8") as f:
                f.write(prompt)
        except Exception as e:
            print(f"[ERRO] Falha ao salvar prompt.txt: {e}")

        if ai_mode == "manual":
            print(f"\n[INFO] O prompt foi salvo em: {manual_prompt_path}")
            print("\n" + "="*60)
            print(f"CHUNK {i+1}/{len(output_texts)}")
            print("="*60)
            print("COPIE O PROMPT ABAIXO (OU DO ARQUIVO GERADO) E COLE NA SUA IA PREFERIDA:")
            print("-" * 20)
            print(prompt)
            print("-" * 20)
            print("="*60)
            print("Cole o JSON de resposta abaixo e pressione ENTER.")
            print("Dica: Se o JSON tiver múltiplas linhas, tente colar tudo de uma vez ou minificado.")
            print("Se preferir, digite 'file' para ler de um arquivo 'tmp/response.json'.")

            user_input = input("JSON ou 'file': ")

            if user_input.lower() == 'file':
                try:
                    response_json_path = os.path.join(project_folder, 'response.json')
                    with open(response_json_path, 'r', encoding='utf-8') as rf:
                        response_text = rf.read()
                except FileNotFoundError:
                    print(f"Arquivo {response_json_path} não encontrado.")
            else:
                response_text = user_input
                if response_text.strip().startswith("{") and not response_text.strip().endswith("}"):
                    print("Parece incompleto. Cole o resto e dê Enter (ou Ctrl+C para cancelar):")
                    try:
                        rest = sys.stdin.read()
                        response_text += rest
                    except:
                        pass

        elif ai_mode == "gemini":
            print(f"Enviando chunk {i+1} para o Gemini (Model: {model_name})...")
            response_text = call_gemini(prompt, api_key, model_name=model_name)
        elif ai_mode == "g4f":
            print(f"Enviando chunk {i+1} para o G4F (Model: {model_name})...")
            response_text = call_g4f(prompt, model_name=model_name)
        elif ai_mode == "local" and local_llm_instance:
            print(f"Processing chunk {i+1} with Local LLM...")
            try:
                output = local_llm_instance.create_chat_completion(
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that outputs only JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=4096,
                    temperature=0.7
                )
                response_text = output['choices'][0]['message']['content']
            except Exception as e:
                print(f"Error evaluating local model: {e}")
                response_text = "{}"

        # --- Save RAW Response for Debugging ---
        try:
            raw_response_path = os.path.join(project_folder, f"response_raw_part_{i+1}.txt")
            with open(raw_response_path, "w", encoding="utf-8") as f:
                f.write(response_text)
            print(f"[DEBUG] Raw response saved to: {raw_response_path}")
        except Exception as e:
            print(f"[WARN] Failed to save raw response: {e}")

        # Processar resposta
        try:
            data = clean_json_response(response_text)
            chunk_segments = data.get("segments", [])
            print(f"Encontrados {len(chunk_segments)} segmentos neste chunk.")
            all_raw_segments.extend(chunk_segments)
        except json.JSONDecodeError:
            print(f"Erro: Resposta inválida.")
        except Exception as e:
            print(f"Erro desconhecido ao processar chunk: {e}")

    # Call the alignment / processing logic
    return process_segments(
        all_raw_segments,
        transcript_segments,
        tempo_minimo,
        tempo_maximo,
        output_count=quantidade_de_virals
    )
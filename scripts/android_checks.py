"""Pure assertions shared by Android automation and regression tests."""
import json
import re
import xml.etree.ElementTree as ET

PACKAGE = "com.ggufchat.app"
PICKERS = {"com.android.documentsui", "com.google.android.documentsui"}


def nodes(xml):
    return list(ET.fromstring(xml).iter("node"))


def has_package(xml, packages):
    return any(n.get("package") in packages for n in nodes(xml))


def position(xml, *, text=None, desc=None, package=None, contains=False, class_name=None, resource_id=None):
    for node in nodes(xml):
        if node.get("enabled") != "true":
            continue
        if package and node.get("package") not in package:
            continue
        if class_name and node.get("class") != class_name:
            continue
        if resource_id and node.get("resource-id") != resource_id:
            continue
        if text is not None:
            value = node.get("text", "").casefold()
            if (text.casefold() not in value) if contains else (text.casefold() != value):
                continue
        if desc is not None and node.get("content-desc", "").casefold() != desc.casefold():
            continue
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if not match:
            continue
        x1, y1, x2, y2 = map(int, match.groups())
        if x2 > x1 and y2 > y1:
            return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def imported(models, filename):
    if not isinstance(models, list):
        raise AssertionError("models.json não é uma lista")
    found = [m for m in models if m.get("fileName") == filename]
    if len(found) != 1 or not found[0].get("path") or not found[0].get("id"):
        raise AssertionError(f"Importação não confirmada ou duplicada: {filename}")
    return found[0]


def fusion(models, vision_name, projector_name):
    vision, projector = imported(models, vision_name), imported(models, projector_name)
    if vision["id"] == projector["id"] or vision.get("mmprojPath") != projector["path"]:
        raise AssertionError("Modelo de visão não está vinculado ao projetor esperado")
    if vision.get("multimodal") is not True:
        raise AssertionError("multimodal não foi persistido")
    return vision["id"], vision["path"], vision["mmprojPath"]


def assistant_reply(chats, chat_id, prompt):
    if not isinstance(chats, list):
        raise AssertionError("chats.json não é uma lista")
    chat = next((c for c in chats if c.get("id") == chat_id), None)
    if not chat or not chat.get("modelPath"):
        raise AssertionError("Conversa/modelo ausente")
    messages = chat.get("messages", [])
    users = [i for i, m in enumerate(messages) if m.get("role") == "user" and m.get("content") == prompt]
    if not users:
        raise AssertionError("O prompt não chegou à conversa esperada")
    replies = [m.get("content", "").strip() for m in messages[users[-1] + 1:]
               if m.get("role") == "assistant"]
    if not replies or not replies[-1]:
        raise AssertionError("Nenhuma resposta de assistant persistida após o prompt")
    return replies[-1]


def generation_completed(log):
    if "GGUF_REPAIR_GENERATION_FAILED" in log or re.search(r"FATAL EXCEPTION|Fatal signal|SIGSEGV", log):
        raise AssertionError("Falha ou crash durante a geração")
    return "GGUF_REPAIR_GENERATION_OK" in log


STATS_RE = re.compile(
    r'GGUF_GENERATION_STATS tokens=(\d+) decode_ns=(\d+) prefill_ns=(\d+) tokens_s=([\d.]+) '
    r'first_token_ns=(-?\d+) prompt_tokens=(\d+) reused_tokens=(\d+) completed=(\d)')
UI_FIRST_RE = re.compile(r'GGUF_UI_FIRST_TEXT send_to_first_ui_ns=(\d+)')
CPU_THREADS_RE = re.compile(r'GGUF_CPU_THREADS requested=(\d+) available=(\d+) capacities=(\d+) resolved=(\d+)')
SOFTWARE_VULKAN_RE = re.compile(
    r'GGUF_VULKAN_SOFTWARE_DEVICE description="([^"]*)" action=cpu_fallback')


def generation_stats(log):
    """Native token counters of the last completed generation in `log`.

    tokens/decode_ns come from the native engine; `tokens_s` is recomputed here
    from those two integers so a formatted log line can never inflate a claim.
    """
    found = STATS_RE.findall(log)
    if not found:
        return None
    tokens, decode_ns, prefill_ns, _printed, first_ns, prompt, reused, completed = found[-1]
    tokens, decode_ns, prefill_ns = int(tokens), int(decode_ns), int(prefill_ns)
    first_ns, prompt, reused = int(first_ns), int(prompt), int(reused)
    return {
        'tokens': tokens,
        'decode_s': decode_ns / 1e9 if decode_ns else 0.0,
        'prefill_s': prefill_ns / 1e9 if prefill_ns else 0.0,
        'tokens_s': tokens / (decode_ns / 1e9) if tokens and decode_ns else 0.0,
        'first_token_s': first_ns / 1e9 if first_ns >= 0 else None,
        'prompt_tokens': prompt,
        'reused_tokens': reused,
        'completed': completed == '1',
    }


WARMUP_RE = re.compile(r'GGUF_WARMUP input_tokens=(\d+) prefilled=(\d+) reused_tokens=(\d+) gpu=(\d) aborted=(\d)')
WARMUP_SKIP_RE = re.compile(r'GGUF_WARMUP_SKIPPED reason=(\w+)')
WARMUP_UI_RE = re.compile(r'GGUF_WARMUP_UI ok=(\d) chars=(\d+)')
WARMUP_TEXT_RE = re.compile(r'GGUF_WARMUP_TEXT ok=(\d) chars=(\d+)')


SEARCH_BUDGET_RE = re.compile(
    r'GGUF_SEARCH_BUDGET total_ms=(\d+) used_ms=(\d+) exhausted=(\d) provider=(\S+)')
SEARCH_RESULT_RE = re.compile(r'GGUF_SEARCH provider=(\S+) results=(\d+) ms=(\d+)')
SEARCH_FAILED_RE = re.compile(r'GGUF_SEARCH_FAILED provider=(\S+) ms=(\d+) error=(.*)')
SEARCH_ANNOUNCED_RE = re.compile(r'GGUF_SEARCH_ANNOUNCED query_pending=1 budget_ms=(\d+)')
SEARCH_PROMPT_RE = re.compile(r'GGUF_SEARCH_PROMPT mode=(\w+)')
SEARCH_ATTEMPT_RE = re.compile(
    r'GGUF_SEARCH_ATTEMPT provider=(\S+) budget_ms=(\d+) remaining_ms=(\d+) connect_ms=(\d+) read_ms=(\d+)')


def search_timing(log):
    """Quanto a busca custou de verdade: orçamento, gasto e o que foi encontrado.

    O teto é o ponto do conserto: sem ele a busca gastava minutos (quatro
    provedores em sequência, cada um com 8 s de conexão e 12 s de leitura) antes de
    o modelo responder. `used_ms` é medido pelo próprio aplicativo.
    """
    found = SEARCH_BUDGET_RE.findall(log)
    if not found:
        return None
    total, used, exhausted, provider = found[-1]
    attempts = [(name, int(budget), int(remaining), int(connect), int(read))
                for name, budget, remaining, connect, read in SEARCH_ATTEMPT_RE.findall(log)]
    hits = SEARCH_RESULT_RE.findall(log)
    failures = SEARCH_FAILED_RE.findall(log)
    announced = SEARCH_ANNOUNCED_RE.findall(log)
    result = {
        'budget_ms': int(total), 'used_ms': int(used), 'exhausted': exhausted == '1',
        'provider': provider,
        'announced_budget_ms': int(announced[-1]) if announced else None,
        'attempts': [name for name, *_ in attempts],
        # A soma das duas fatias de uma tentativa nunca passa do restante do
        # orçamento — é a garantia central do conserto, no relógio do aparelho.
        'attempt_slices_within_budget': all(
            connect + read <= remaining for _, _, remaining, connect, read in attempts),
        'sources': int(hits[-1][1]) if hits else 0,
        'prompt_mode': SEARCH_PROMPT_RE.findall(log)[-1] if SEARCH_PROMPT_RE.findall(log) else None,
        'error': failures[-1][2] if failures else None,
    }
    return result


def search_panel(chats, chat_id, prompt):
    """O painel de proveniência persistido na resposta — a fonte do que a tela mostra."""
    if not isinstance(chats, list):
        return None
    chat = next((c for c in chats if c.get('id') == chat_id), None)
    if not chat:
        return None
    messages = chat.get('messages', [])
    users = [i for i, m in enumerate(messages)
             if m.get('role') == 'user' and m.get('content') == prompt]
    if not users:
        return None
    for message in messages[users[-1] + 1:]:
        if message.get('role') != 'assistant':
            continue
        raw = message.get('searchSources')
        if raw is None:
            continue
        # Na mensagem persistida as fontes são um OBJETO JSON; em memória o app
        # guarda a string (Message.fromJson → SearchTool.read). Aceitar só uma das
        # formas reprovava o aplicativo por culpa do próprio teste.
        if isinstance(raw, dict):
            return raw
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None
    return None


CONTEXT_TUNING_RE = re.compile(
    r'GGUF_CONTEXT_TUNING batch=(\d+) ubatch=(\d+) threads=(\d+) prefix_cache_supported=(\d)')

# Campos opcionais: rodadas antigas não os tinham, e a falta deles não pode
# invalidar o que aquelas rodadas mediram.
KV_CACHE_RE = re.compile(r'GGUF_CONTEXT_TUNING .*?kv=(\w+) fa_requested=(\w+)')


def context_tuning(log):
    """O que o motor REALMENTE usou no contexto (lote, sub-lote, threads).

    Um ajuste medido sem este registro não vale nada: sem ele não se sabe qual
    configuração produziu o número.
    """
    found = CONTEXT_TUNING_RE.findall(log)
    if not found:
        return None
    batch, ubatch, threads, cache = found[-1]
    return {'batch': int(batch), 'ubatch': int(ubatch), 'threads': int(threads),
            'prefix_cache_supported': cache == '1'}


def kv_cache(log):
    """Tipo do cache K/V e atenção flash pedidos, como o motor registrou.

    O experimento de cache quantizado só vale se o log provar que a configuração
    pedida foi a usada: `setprop` sem efeito não pode virar "ganho medido".
    """
    found = KV_CACHE_RE.findall(log)
    if not found:
        return None
    kv, flash = found[-1]
    return {'kv': kv, 'flash_attn_requested': flash}


SEARCH_CACHE_RE = re.compile(
    r'GGUF_SEARCH_CACHE hit=1 provider=(\S+) results=(\d+) age_ms=(\d+) ttl_ms=(\d+)')
SEARCH_RACE_RE = re.compile(
    r'GGUF_SEARCH_RACE winner=(\S+) results=(\d+) candidates_pending=(\d+) candidates=(\d+)')


def search_cache_hit(log):
    """A consulta repetida saiu da memória? (prova do cache, com a idade do resultado.)"""
    found = SEARCH_CACHE_RE.findall(log)
    if not found:
        return None
    provider, results, age, ttl = found[-1]
    return {'provider': provider, 'results': int(results), 'age_ms': int(age), 'ttl_ms': int(ttl)}


def search_race_winner(log):
    """Quem venceu a corrida de provedores e quantos candidatos ainda corriam."""
    found = SEARCH_RACE_RE.findall(log)
    if not found:
        return None
    winner, results, pending, candidates = found[-1]
    return {'winner': winner, 'results': int(results), 'pending': int(pending),
            'candidates': int(candidates)}


def pref_value(xml, name):
    """Valor de um ajuste persistido, nos dois formatos que o Android escreve.

    O `shared_prefs` do aplicativo guarda inteiros como
    `<int name="contextSize" value="1024" />` — o valor é atributo, não o texto do
    elemento. Uma busca por `>1024<` nunca encontraria nada e o teste reprovaria o
    aplicativo por causa do formato do arquivo.
    """
    for pattern in (rf'name="{re.escape(name)}"\s+value="([^"]*)"',
                    rf'name="{re.escape(name)}"\s*>([^<]*)<'):
        found = re.search(pattern, xml)
        if found:
            return found.group(1)
    return None


def warmup_state(log):
    """O que o aquecimento de prefixo realmente fez nesta etapa.

    `ran` só é verdadeiro com o contador nativo (`GGUF_WARMUP`); um simples
    "ok=1" da camada Java não conta como aquecimento. `text_repeats` conta as
    passadas de digitação, para a evidência mostrar que o KV cresceu junto.
    """
    ran = WARMUP_RE.findall(log)
    skips = WARMUP_SKIP_RE.findall(log)
    state = {'ran': bool(ran), 'skipped': skips[-1] if skips else None,
             'ui_ok': bool(WARMUP_UI_RE.search(log)), 'typed_passes': len(WARMUP_TEXT_RE.findall(log))}
    if ran:
        tokens, prefilled, reused, gpu, aborted = (int(value) for value in ran[-1])
        state.update({'input_tokens': tokens, 'prefilled': prefilled,
                      'reused_tokens': reused, 'gpu': bool(gpu), 'aborted': bool(aborted)})
    return state


def ui_first_text_s(log):
    """Tap-to-visible-text wait measured on the Android main thread."""
    found = UI_FIRST_RE.findall(log)
    return int(found[-1]) / 1e9 if found else None


def software_vulkan_refused(log):
    """The device offered a software rasteriser as Vulkan and the app used the CPU."""
    found = SOFTWARE_VULKAN_RE.findall(log)
    return found[-1] if found else None


def cpu_threads(log):
    """Quantas threads o motor realmente usou, e o que o aparelho oferecia."""
    found = CPU_THREADS_RE.findall(log)
    if not found:
        return None
    requested, available, capacities, resolved = (int(value) for value in found[-1])
    return {'requested': requested, 'available': available,
            'capacities': capacities, 'resolved': resolved}


BACKEND_EXECUTION_RE = re.compile(r'GGUF_BACKEND_EXECUTION backend=(cpu|vulkan)')
OFFLOAD_RE = re.compile(r"offloaded\s+[1-9]\d*(?:/\d+)?\s+layers?\s+to\s+GPU", re.I)


def backend_execution(log):
    """Backend que executa, declarado pelo nativo no momento da decisão.

    É a única classificação confiável: no caminho de recusa do Vulkan por software
    o carregador já registrou "offloaded N/N layers to GPU" apenas porque o pedido
    de camadas era INT_MAX, mesmo com a lista de dispositivos esvaziada e a
    execução na CPU.
    """
    found = BACKEND_EXECUTION_RE.findall(log)
    return found[-1] if found else None


def gpu_offloaded(log):
    # Merecer carregar libggml-vulkan.so/SwiftShader NÃO é prova de inferência em GPU.
    declared = backend_execution(log)
    if declared is not None:
        return declared == 'vulkan'
    return bool(OFFLOAD_RE.search(log))


def basic_response_quality(greeting, arithmetic):
    """Conservative sanity check for the suite's two fixed prompts, not a benchmark."""
    if not re.search(r'\b(hello|hi|hey|greetings|good morning|good afternoon|good evening)\b', greeting, re.I):
        raise AssertionError('Resposta não contém uma saudação pertinente ao primeiro pedido')
    answer = arithmetic.casefold().replace('*', '').replace('`', '').strip(' \n.!')
    accepted = {'4', 'four', '2+2=4', '2 + 2 = 4', 'two + two = four', 'two plus two is four',
                'two plus two equals four', 'two plus two is 4', 'two plus two equals 4',
                'the answer is 4', 'the answer is four'}
    if answer not in accepted:
        raise AssertionError('Resposta à pergunta 2 + 2 não corresponde à resposta simples esperada: 4')
    return True


def vulkan_offloaded(log):
    """Require initialized Vulkan plus actual positive layer offload, not availability."""
    initialized = re.search(r'registered backend Vulkan|ggml_vulkan: Found [1-9]', log, re.I)
    # A GPU load may fail during context creation, then EngineManager retries CPU.
    # Evidence from that abandoned attempt must not approve the CPU generation.
    loads = list(re.finditer(r'llama_model_loader: loaded meta data', log))
    current = log[loads[-1].start():] if loads else log
    counts = re.findall(r'offloaded\s+(\d+)(?:/\d+)?\s+layers?\s+to\s+GPU', current, re.I)
    return bool(initialized and counts and int(counts[-1]) > 0)


def image_prefill_records(log, images):
    """A source image can become several native vision crops/chunks.
    Keep the exact source-image count AND require positive evaluated tokens.
    """
    records = re.findall(r'GGUF_IMAGE_EVALUATED tokens=([1-9]\d*) backend=(\w+)', log)
    assert images > 0 and len(records) >= images, records
    counts = re.findall(r'GGUF_MEDIA_PREFILL images=(\d+) tokens=([1-9]\d*) positions=([1-9]\d*)', log)
    assert len(counts) == 1 and int(counts[0][0]) == images, counts
    return records


def select_exact_documents(d, names):
    """Use document selection icons, not long-press range/exclusive selection."""
    import xml.etree.ElementTree as ET
    assert names and len(set(names)) == len(names)
    def rows():
        xml=d.ui();root=ET.fromstring(xml)
        parents={child:parent for parent in root.iter() for child in parent}
        found={}
        for node in root.iter('node'):
            name=node.get('text')
            if name not in names or node.get('package') not in PICKERS:continue
            row=node
            while row in parents:
                if row.get('resource-id','').endswith('/item_root'):break
                row=parents[row]
            if not row.get('resource-id','').endswith('/item_root'):
                # Current Android DocumentsUI exposes document selection on the
                # thumbnail at the left of the named row, not its Open action.
                row=parents.get(node,node)
            found[name]=row
        return xml,found
    for name in names:
        for attempt in range(3):
            xml,found=rows();assert name in found,name
            row=found[name]
            if row.get('selected')=='true' or any(n.get('checked')=='true' for n in row.iter()):break
            # Use the current title Y (list headers move when selection starts).
            x,y=position(xml,text=name,package=PICKERS)
            left=int(re.findall(r'\d+',row.get('bounds','[0,0][720,1280]'))[0])
            d.shell(f'input tap {left+48} {y}')
            def selected():
                _,current=rows();r=current.get(name)
                return r is not None and (r.get('selected')=='true' or any(n.get('checked')=='true' for n in r.iter()))
            try:d.wait(selected,'named document selected: '+name,timeout=8);break
            except AssertionError:
                if attempt==2:raise
    d.wait(lambda: position(d.ui(), text=f'{len(names)} selected', package=PICKERS), 'contagem exata de arquivos selecionados')


def active_wake_locks(power_dump):
    """Read only currently held locks, NOT Android's retained Wake Lock Log.
    A missing section is an error, never evidence that a lease was released.
    """
    match=re.search(r'(?m)^[ \t]*Wake Locks: size=(\d+)[ \t]*\r?$',power_dump)
    if not match:raise AssertionError('Active Wake Locks section missing from dumpsys power')
    if int(match.group(1))==0:return ''
    body=power_dump[match.end():].lstrip('\r\n')
    return re.split(r'\n[ \t]*\n',body,maxsplit=1)[0]


def completed_after_actual_sleep(log):
    """A fast model can finish AFTER screen-off but BEFORE the observer polls.
    Compare the system's actual Sleeping event with the native completion instead.
    """
    sleep=re.search(r'(?m)^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+) .*PowerManagerService: Sleeping \(',log)
    done=re.search(r'(?m)^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+) .*GGUF_NATIVE_COMPLETE',log)
    return bool(sleep and done and done.group(1)>sleep.group(1))

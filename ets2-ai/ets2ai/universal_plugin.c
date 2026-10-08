/* ---------------------------------------------------------------------------
 * universal_plugin.c — DLL de telemetria UNIVERSAL do ETS2-AI
 * ---------------------------------------------------------------------------
 * UMA DLL para TODOS os ETS2/ATS com SDK de telemetria (interface 1.00/1.01,
 * patch 1.36 ate o futuro): a DLL registra TODOS os canais da era
 * "truck.*" e o jogo ativa os que conhecer — canal que nao existe no jogo
 * so falha o registro (inofensivo). Isso elimina a matrix de releases:
 * qualquer jogo novo continua funcionando SEM DLL nova.
 *
 * Como o plugin oficial (RenCloud, MIT — a quem este codigo deve a
 * arquitetura), escreve a telemetria na memoria compartilhada
 * "Local\SCSTelemetry" — MAS no layout do leitor do ETS2-AI
 * (ets2ai/telemetry.py, classe TelemetryMap), marcado com um MAGIC nosso
 * (offset 1472) para o leitor saber a origem. Jogos < 1.36 seguem no
 * banco oficial (RenCloud + nlhans) pela rotacao automatica.
 *
 * Compilar (MSVC):
 *   cl /LD /O2 /W4 /DUNICODE universal_plugin.c /DEF:universal.def \
 *      /Fe:scs-telemetry.dll /link kernel32.lib user32.lib
 *
 * Log proprio: <raiz do jogo>\game-ets2ai-telemetry.log (a raiz e 3 niveis
 * acima de bin\win_x64\plugins\). Tambem escreve no game.log.txt do jogo
 * via a funcao log do SDK.
 * ------------------------------------------------------------------------- */

#include <windows.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>

#define SCS_CDECL __cdecl

/* ---- layout TelemetryMap (ets2ai/telemetry.py) — offsets verificados --- */
#define MAP_SIZE        32768
#define OFF_SDK_ACTIVE   0    /* bool   */
#define OFF_PAUSED       4    /* bool   */
#define OFF_TIME         8    /* u64    ticks (frame_start: simulation_time) */
#define OFF_PLUGIN_REV  40    /* u32    */
#define OFF_VER_MAJOR   44    /* u32    */
#define OFF_VER_MINOR   48    /* u32    */
#define OFF_GAME_ID     52    /* u32    1=ets2 2=ats */
#define OFF_GEAR       504    /* s32    */
#define OFF_FUEL_CAP   704    /* f32    litros */
#define OFF_SPEED      948    /* f32    m/s */
#define OFF_ENGINE_RPM 952    /* f32    */
#define OFF_USER_STEER 956    /* f32    -1..1 (+ = direita) */
#define OFF_THROTTLE   960    /* f32    0..1 */
#define OFF_BRAKE      964    /* f32    0..1 */
#define OFF_FUEL      1000    /* f32    litros absolutos */
#define OFF_ODOMETER  1056    /* f32    km */
#define OFF_ROUTE_DIST 1060   /* f32    metros ate o destino */
#define OFF_ROUTE_TIME 1064   /* f32    s */
#define OFF_SPEED_LIM  1068   /* f32    m/s */
#define OFF_MAGIC     1472    /* u32    AUI1 = origem ETS2-AI universal */
#define OFF_SPECIAL_JOB 1565  /* bool */
#define OFF_PARK_BRAKE 1566   /* bool */
#define OFF_ENGINE_ON  1576   /* bool */
#define OFF_WORLD_X   2200    /* f64 */
#define OFF_WORLD_Y   2208    /* f64 */
#define OFF_WORLD_Z   2216    /* f64 */
#define OFF_ROT_X     2224    /* f32 heading (0..1 = 0..360) */
#define OFF_ROT_Y     2232    /* f32 pitch */
#define OFF_ROT_Z     2240    /* f32 roll */
#define OFF_ON_JOB    4300    /* bool */

#define UNIVERSAL_MAGIC 0x31495541u          /* "AUI1" little-endian */
#define UNIVERSAL_TAG   "ets2ai-universal-v1"
#define UNIVERSAL_REVID 15                   /* >= 12 (exigido pelo parse) */
#define MMF_NAME        L"Local\\SCSTelemetry"

/* ---- SCS SDK: o minimo da interface 1.00/1.01 (scssdk*.h) -------------- */
typedef int32_t   scs_s32_t;
typedef uint32_t  scs_u32_t;
typedef uint64_t  scs_u64_t;
typedef float     scs_float_t;
typedef double    scs_double_t;
typedef const char *scs_string_t;
typedef void     *scs_context_t;
typedef uint32_t  scs_value_type_t;
typedef uint32_t  scs_event_t;
typedef int       scs_result_t;

#define SCS_RESULT_ok         0
#define SCS_RESULT_unsupported (-1)
#define SCS_U32_NIL           0xFFFFFFFFu

#define SCS_VALUE_TYPE_bool       1u
#define SCS_VALUE_TYPE_s32        2u
#define SCS_VALUE_TYPE_u32        3u
#define SCS_VALUE_TYPE_float      5u
#define SCS_VALUE_TYPE_fvector    7u
#define SCS_VALUE_TYPE_dplacement 11u

#define SCS_TELEMETRY_EVENT_frame_start   1u
#define SCS_TELEMETRY_EVENT_paused        3u
#define SCS_TELEMETRY_EVENT_started       4u
#define SCS_TELEMETRY_EVENT_configuration 5u
#define SCS_TELEMETRY_EVENT_gameplay      6u

#define SCS_TELEMETRY_VERSION_1_00  0x00010000u
#define SCS_TELEMETRY_VERSION_1_01  0x00010001u

typedef struct { float x, y, z; }                scs_fvector_t;
typedef struct { double x, y, z; }               scs_dvector_t;
typedef struct { float heading, pitch, roll; }   scs_euler_t;
typedef struct { scs_dvector_t position; scs_euler_t orientation;
                 scs_u32_t _padding; }           scs_dplacement_t;

typedef struct {
    scs_value_type_t type;
    scs_u32_t        _padding;
    union {
        uint8_t         value_bool;
        scs_s32_t       value_s32;
        scs_u32_t       value_u32;
        scs_u64_t       value_u64;
        float           value_float;
        double          value_double;
        scs_fvector_t   value_fvector;
        scs_dvector_t   value_dvector;
        scs_euler_t     value_euler;
        scs_dplacement_t value_dplacement;
        scs_string_t    value_string;
    };
} scs_value_t;                                   /* 48 bytes (SDK) */

typedef struct {
    scs_string_t name;
    scs_u32_t    index;
#ifdef _WIN64
    scs_u32_t    _padding;
#endif
    scs_value_t  value;
} scs_named_value_t;

typedef struct {
    scs_string_t id;
    const scs_named_value_t *attributes;         /* termina com name == NULL */
} scs_telemetry_configuration_t;

typedef struct {
    scs_u32_t flags;
    scs_u32_t _padding;
    scs_u64_t render_time;
    scs_u64_t simulation_time;
} scs_telemetry_frame_start_t;

typedef void (*scs_log_t)(scs_u32_t type, const scs_string_t message);
typedef void (*scs_telemetry_event_callback_t)(
    const scs_event_t event, const void *const event_info,
    const scs_context_t context);
typedef void (*scs_telemetry_channel_callback_t)(
    const scs_string_t name, const scs_u32_t index,
    const scs_value_t *const value, const scs_context_t context);
typedef scs_result_t (*scs_telemetry_register_for_event_t)(
    const scs_event_t event, const scs_telemetry_event_callback_t callback,
    const scs_context_t context);
typedef scs_result_t (*scs_telemetry_register_for_channel_t)(
    const scs_string_t name, const scs_u32_t index,
    const scs_value_type_t type, const scs_u32_t flags,
    const scs_telemetry_channel_callback_t callback,
    const scs_context_t context);

typedef struct {
    scs_string_t game_name;
    scs_string_t game_id;
    scs_u32_t    game_version;                   /* versao da API, nao do patch */
#ifdef _WIN64
    scs_u32_t    _padding;
#endif
    scs_log_t    log;
} scs_sdk_init_params_v100_t;

typedef struct {
    scs_sdk_init_params_v100_t common;
    scs_telemetry_register_for_event_t    register_for_event;
    scs_telemetry_register_for_channel_t  register_for_channel;
} scs_telemetry_init_params_v100_t;              /* 1.01 = typedef da 1.00 */

/* ---- estado global ------------------------------------------------------ */
static HANDLE          g_mapping = NULL;
static unsigned char  *g_map     = NULL;
static HANDLE          g_logfile = INVALID_HANDLE_VALUE;
static scs_log_t       g_game_log = NULL;

/* ---- log proprio (<raiz do jogo>\game-ets2ai-telemetry.log) ------------- */
static void ulog(const char *msg) {
    if (g_logfile != INVALID_HANDLE_VALUE) {
        DWORD w = 0;
        WriteFile(g_logfile, msg, (DWORD)lstrlenA(msg), &w, NULL);
        WriteFile(g_logfile, "\r\n", 2, &w, NULL);
    }
    if (g_game_log)                              /* vai pro game.log.txt */
        g_game_log(0 /* SCS_LOG_TYPE_message */, msg);
}

/* ---- escrita no mapa (offsets verificados) ------------------------------ */
static void put_u32(size_t off, scs_u32_t v)   { if (g_map) *(scs_u32_t *)(g_map + off) = v; }
static void put_i32(size_t off, scs_s32_t v)   { if (g_map) *(scs_s32_t *)(g_map + off) = v; }
static void put_f32(size_t off, float v)       { if (g_map) *(float *)(g_map + off) = v; }
static void put_f64(size_t off, double v)      { if (g_map) *(double *)(g_map + off) = v; }
static void put_bool(size_t off, int v)        { if (g_map) g_map[off] = (unsigned char)(v ? 1 : 0); }

/* ---- callbacks de CANAL: o context e o OFFSET de destino ---------------- */
static void SCS_CDECL on_channel(const scs_string_t name, const scs_u32_t index,
                                 const scs_value_t *const value,
                                 const scs_context_t context) {
    (void)name; (void)index;
    if (!g_map || !value) return;
    const size_t off = (size_t)(uintptr_t)context;
    /* OBS: os SCS_VALUE_TYPE_* do SDK sao VARIABLES const — em C nao podem
     * ser case (so constante inteira). Compara com os valores literais. */
    if (value->type == SCS_VALUE_TYPE_bool)
        put_bool(off, value->value_bool != 0);
    else if (value->type == SCS_VALUE_TYPE_s32)
        put_i32(off, value->value_s32);
    else if (value->type == SCS_VALUE_TYPE_u32)
        put_u32(off, value->value_u32);
    else if (value->type == SCS_VALUE_TYPE_float)
        put_f32(off, value->value_float);
    else if (value->type == SCS_VALUE_TYPE_dplacement) {
        put_f64(OFF_WORLD_X, value->value_dplacement.position.x);
        put_f64(OFF_WORLD_Y, value->value_dplacement.position.y);
        put_f64(OFF_WORLD_Z, value->value_dplacement.position.z);
        put_f32(OFF_ROT_X,   value->value_dplacement.orientation.heading);
        put_f32(OFF_ROT_Y,   value->value_dplacement.orientation.pitch);
        put_f32(OFF_ROT_Z,   value->value_dplacement.orientation.roll);
    }                                             /* outros tipos: ignora */
}

/* ---- callbacks de EVENTO ------------------------------------------------ */
static void SCS_CDECL on_frame_start(const scs_event_t event,
                                     const void *const event_info,
                                     const scs_context_t context) {
    (void)event; (void)context;
    if (!g_map || !event_info) return;
    const scs_telemetry_frame_start_t *fs =
        (const scs_telemetry_frame_start_t *)event_info;
    *(scs_u64_t *)(g_map + OFF_TIME) = fs->simulation_time;
}

static void SCS_CDECL on_pause(const scs_event_t event,
                               const void *const event_info,
                               const scs_context_t context) {
    (void)event_info; (void)context;
    put_bool(OFF_PAUSED, event == SCS_TELEMETRY_EVENT_paused);
}

static void SCS_CDECL on_configuration(const scs_event_t event,
                                       const void *const event_info,
                                       const scs_context_t context) {
    (void)event; (void)context;
    if (!g_map || !event_info) return;
    const scs_telemetry_configuration_t *cfg =
        (const scs_telemetry_configuration_t *)event_info;
    if (!cfg->id) return;
    if (lstrcmpA(cfg->id, "job") == 0) {
        /* atributos vazios = job cancelado/concluido (igual ao RenCloud) */
        const int tem_atributos =
            (cfg->attributes && cfg->attributes->name != NULL);
        put_bool(OFF_ON_JOB, tem_atributos);
    } else if (lstrcmpA(cfg->id, "truck") == 0) {
        for (const scs_named_value_t *a = cfg->attributes;
             a && a->name != NULL; ++a) {
            if (lstrcmpA(a->name, "fuel.capacity") == 0 &&
                a->value.type == SCS_VALUE_TYPE_float)
                put_f32(OFF_FUEL_CAP, a->value.value_float);
            (void)a; /* value_float: union anonima do scs_value_t (direto) */
        }
    }
}

static void SCS_CDECL on_gameplay(const scs_event_t event,
                                  const void *const event_info,
                                  const scs_context_t context) {
    (void)event; (void)context;
    if (!g_map || !event_info) return;
    const scs_telemetry_configuration_t *ev =
        (const scs_telemetry_configuration_t *)event_info;
    if (ev->id && (lstrcmpA(ev->id, "job.delivered") == 0 ||
                   lstrcmpA(ev->id, "job.cancelled") == 0))
        put_bool(OFF_ON_JOB, 0);
}

/* ---- inicializacao (chamada pelo JOGO) ---------------------------------- */
__declspec(dllexport) scs_result_t SCS_CDECL scs_telemetry_init(
    const scs_u32_t version, const void *const params) {
    if (version != SCS_TELEMETRY_VERSION_1_00 &&
        version != SCS_TELEMETRY_VERSION_1_01)
        return SCS_RESULT_unsupported;           /* interface futura: recusa */
    const scs_telemetry_init_params_v100_t *p =
        (const scs_telemetry_init_params_v100_t *)params;
    if (!p || !p->common.log) return -7 /* SCS_RESULT_generic_error */;

    g_game_log = p->common.log;

    /* memoria compartilhada: MESMO nome/layOUT do plugin oficial */
    g_mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL,
                                   PAGE_READWRITE, 0, MAP_SIZE, MMF_NAME);
    if (!g_mapping) return -7;
    g_map = (unsigned char *)MapViewOfFile(g_mapping, FILE_MAP_ALL_ACCESS,
                                           0, 0, MAP_SIZE);
    if (!g_map) { CloseHandle(g_mapping); g_mapping = NULL; return -7; }
    ZeroMemory(g_map, MAP_SIZE);

    put_bool(OFF_SDK_ACTIVE, 1);
    put_bool(OFF_PAUSED, 1);
    put_u32(OFF_PLUGIN_REV, UNIVERSAL_REVID);
    put_u32(OFF_VER_MAJOR, p->common.game_version >> 16);
    put_u32(OFF_VER_MINOR, p->common.game_version & 0xFFFF);
    if (p->common.game_id && lstrcmpA(p->common.game_id, "eurotrucks2") == 0)
        put_u32(OFF_GAME_ID, 1);                 /* ETS2 */
    else if (p->common.game_id && lstrcmpA(p->common.game_id, "amtrucks") == 0)
        put_u32(OFF_GAME_ID, 2);                 /* ATS */
    else
        put_u32(OFF_GAME_ID, 0);
    put_u32(OFF_MAGIC, UNIVERSAL_MAGIC);

    /* eventos */
    if (p->register_for_event(SCS_TELEMETRY_EVENT_frame_start,
                              on_frame_start, NULL) != SCS_RESULT_ok ||
        p->register_for_event(SCS_TELEMETRY_EVENT_paused,
                              on_pause, NULL) != SCS_RESULT_ok ||
        p->register_for_event(SCS_TELEMETRY_EVENT_started,
                              on_pause, NULL) != SCS_RESULT_ok ||
        p->register_for_event(SCS_TELEMETRY_EVENT_configuration,
                              on_configuration, NULL) != SCS_RESULT_ok)
        return -7;
    if (p->common.game_version >= 0x0001000E)    /* gameplay: telemetria 1.14+ */
        p->register_for_event(SCS_TELEMETRY_EVENT_gameplay,
                              on_gameplay, NULL);

    /* canais: registra TUDO da era truck.* — o jogo ativa os que conhecer
     * (canal inexistente so falha o registro: inofensivo). UNIVERSAL. */
    struct { const char *name; scs_value_type_t type; size_t off; } canais[] = {
        { "game.time",                     SCS_VALUE_TYPE_u32,  OFF_TIME },
        { "truck.speed",                   SCS_VALUE_TYPE_float, OFF_SPEED },
        { "truck.fuel.amount",             SCS_VALUE_TYPE_float, OFF_FUEL },
        { "truck.input.steering",          SCS_VALUE_TYPE_float, OFF_USER_STEER },
        { "truck.input.throttle",          SCS_VALUE_TYPE_float, OFF_THROTTLE },
        { "truck.input.brake",             SCS_VALUE_TYPE_float, OFF_BRAKE },
        { "truck.engine.enabled",          SCS_VALUE_TYPE_bool,  OFF_ENGINE_ON },
        { "truck.brake.parking",           SCS_VALUE_TYPE_bool,  OFF_PARK_BRAKE },
        { "truck.world.placement",         SCS_VALUE_TYPE_dplacement, 0 },
        { "truck.engine.gear",             SCS_VALUE_TYPE_s32,   OFF_GEAR },
        { "truck.engine.rpm",              SCS_VALUE_TYPE_float, OFF_ENGINE_RPM },
        { "truck.odometer",                SCS_VALUE_TYPE_float, OFF_ODOMETER },
        { "truck.navigation.distance",     SCS_VALUE_TYPE_float, OFF_ROUTE_DIST },
        { "truck.navigation.time",         SCS_VALUE_TYPE_float, OFF_ROUTE_TIME },
        { "truck.navigation.speed.limit",  SCS_VALUE_TYPE_float, OFF_SPEED_LIM },
    };
    for (size_t i = 0; i < sizeof(canais) / sizeof(canais[0]); ++i)
        p->register_for_channel(canais[i].name, SCS_U32_NIL, canais[i].type,
                                0x00000002 /* FLAG_no_value */,
                                on_channel, (scs_context_t)canais[i].off);

    ulog("[universal] ETS2-AI telemetry ATIVA (" UNIVERSAL_TAG
         ") - 1 DLL para TODAS as versoes (1.36+); layout com magic proprio; "
         "veja game-ets2ai-telemetry.log na raiz do jogo");
    return SCS_RESULT_ok;
}

__declspec(dllexport) scs_result_t SCS_CDECL scs_telemetry_shutdown(void) {
    put_bool(OFF_SDK_ACTIVE, 0);
    put_u32(OFF_MAGIC, 0);
    if (g_map) { UnmapViewOfFile(g_map); g_map = NULL; }
    if (g_mapping) { CloseHandle(g_mapping); g_mapping = NULL; }
    if (g_logfile != INVALID_HANDLE_VALUE) {
        CloseHandle(g_logfile); g_logfile = INVALID_HANDLE_VALUE;
    }
    return SCS_RESULT_ok;
}

/* ---- log proprio na raiz do jogo (3 niveis acima de
 *      bin\win_x64\plugins\scs-telemetry.dll) ------------------------------ */
static void abre_log_proprio(HMODULE module) {
    wchar_t path[MAX_PATH + 1];
    DWORD n = GetModuleFileNameW(module, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return;
    /* sobe 3 diretorios: plugins -> win_x64 -> bin -> raiz do jogo */
    for (int up = 0; up < 3; ++up) {
        wchar_t *barra = wcsrchr(path, L'\\');
        if (!barra) return;
        *barra = L'\0';
    }
    if (lstrcatW(path, L"\\game-ets2ai-telemetry.log") == NULL) return;
    g_logfile = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ, NULL,
                            CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        abre_log_proprio(module);
    }
    return TRUE;
}

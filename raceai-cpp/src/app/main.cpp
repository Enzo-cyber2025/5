// main.cpp — interface gráfica (Win32 + GDI, sem bibliotecas externas).
//
// O jogo inteiro roda com o que o Windows já tem: janelas e controles nativos
// (botões, sliders, caixas de texto) e um canvas desenhado na memória (GDI).
// O CPython, quando existe na pasta `python/`, é carregado em tempo de execução
// para a IA colada pelo usuário — sem ele o jogo continua funcionando.
#ifndef UNICODE
#define UNICODE
#define _UNICODE
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#include <windows.h>
#include <commctrl.h>
#include <commdlg.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "app_state.hpp"

using namespace raceai;

// ------------------------------------------------------------------ janela
static const wchar_t* kClasse = L"RaceAI2D";
static const int kPainelW = 420;
static const int kTimer = 1;

static HWND g_hwnd = nullptr;
static HWND g_edita_python = nullptr;
static HWND g_botao_chave = nullptr;
static HWND g_texto_metricas = nullptr;
static HWND g_texto_corrida = nullptr;
static HFONT g_fonte = nullptr;
static HFONT g_fonte_titulo = nullptr;
static HFONT g_fonte_mono = nullptr;
static AppState g_app;
static double g_zoom = 6.0;
static bool g_seguir = true;
static int g_foco = 0;              // carro em foco na câmera

// ------------------------------------------------------------------ helpers
static std::wstring wide(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), int(s.size()), nullptr, 0);
    std::wstring out(size_t(n), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), int(s.size()), &out[0], n);
    return out;
}

static std::string narrow(const std::wstring& s) {
    if (s.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, s.c_str(), int(s.size()), nullptr, 0, nullptr, nullptr);
    std::string out(size_t(n), '\0');
    WideCharToMultiByte(CP_UTF8, 0, s.c_str(), int(s.size()), &out[0], n, nullptr, nullptr);
    return out;
}

static HWND rotulo(HWND pai, int x, int y, int w, int h, const wchar_t* txt,
                   HFONT f = nullptr, COLORREF cor = RGB(220, 226, 235)) {
    HWND hw = CreateWindowW(L"static", txt, WS_CHILD | WS_VISIBLE | SS_LEFT, x, y, w, h, pai,
                            nullptr, GetModuleHandle(nullptr), nullptr);
    if (f) SendMessageW(hw, WM_SETFONT, (WPARAM)f, TRUE);
    (void)cor;
    return hw;
}

// formata um "nome  1.23" sem depender de swprintf (que varia no MinGW)
static std::wstring rotulo_valor(const std::wstring& nome, double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.2f", v);
    return nome + L"  " + wide(std::string(buf));
}

static HWND botao(HWND pai, int id, int x, int y, int w, int h, const wchar_t* txt) {
    HWND hw = CreateWindowW(L"button", txt, WS_CHILD | WS_VISIBLE | WS_TABSTOP, x, y, w, h, pai,
                            (HMENU)(intptr_t)id, GetModuleHandle(nullptr), nullptr);
    SendMessageW(hw, WM_SETFONT, (WPARAM)g_fonte, TRUE);
    return hw;
}

struct Slider {
    HWND barra = nullptr;
    HWND texto = nullptr;
    double* valor = nullptr;
    double escala = 100.0;
    std::wstring nome;
    void atualiza() {
        if (!barra) return;
        SendMessageW(barra, TBM_SETPOS, TRUE, (LPARAM)int(std::lround(*valor * escala)));
        SetWindowTextW(texto, rotulo_valor(nome, *valor).c_str());
    }
};
static std::vector<Slider> g_sliders;

static HWND cria_slider(HWND pai, int x, int y, int w, const wchar_t* nome, double* valor,
                        double min, double max, double escala) {
    Slider s;
    s.valor = valor;
    s.escala = escala;
    s.nome = nome;
    s.texto = rotulo(pai, x, y, w, 18, nome);
    s.barra = CreateWindowW(TRACKBAR_CLASSW, L"", WS_CHILD | WS_VISIBLE | TBS_AUTOTICKS,
                            x, y + 18, w, 22, pai, nullptr, GetModuleHandle(nullptr), nullptr);
    SendMessageW(s.barra, TBM_SETRANGE, TRUE, MAKELONG(int(min * escala), int(max * escala)));
    SendMessageW(s.barra, TBM_SETPOS, TRUE, (LPARAM)int(std::lround(*valor * escala)));
    g_sliders.push_back(s);
    g_sliders.back().atualiza();
    return s.barra;
}

// ------------------------------------------------------------------ ids
enum {
    ID_CORRIDA = 1001, ID_TREINO, ID_MENU, ID_INICIAR, ID_PAUSAR, ID_REINICIAR,
    ID_SALVAR, ID_CARREGAR, ID_APLICAR_PY, ID_PISTA, ID_CARRO, ID_LIMPAR_PY,
    ID_EXEMPLO_PY, ID_NOVO, ID_ADD_MODELO, ID_AJUDA, ID_SAIR, ID_VOLTAR,
    ID_ABRIR_PY, ID_SALVAR_PY,
    ID_RECOMPENSA_PADRAO, ID_ZOOM_MAIS, ID_ZOOM_MENOS, ID_CHAVE_MODO
};

// ------------------------------------------------------------------ canvas
struct Camera { double x = 0.0, y = 0.0, z = 6.0; };
static Camera g_cam;

static void pinta_canvas(HDC hdc, int x0, int y0, int w, int h) {
    // fundo
    HBRUSH fundo = CreateSolidBrush(RGB(14, 17, 22));
    RECT r = {x0, y0, x0 + w, y0 + h};
    FillRect(hdc, &r, fundo);
    DeleteObject(fundo);

    const Track* trk = nullptr;
    if (g_app.mode == Mode::Corrida && g_app.race.sim) trk = &g_app.race.sim->track;
    else if (g_app.trainer) trk = &g_app.trainer->track;
    if (!trk || trk->n() < 4) return;

    const double z = g_cam.z;
    const double cx = x0 + w * 0.5;
    const double cy = y0 + h * 0.5;
    auto sx = [&](double wx) { return int(cx + (wx - g_cam.x) * z); };
    auto sy = [&](double wy) { return int(cy - (wy - g_cam.y) * z); };

    // ------------------------------------------------------- asfalto
    std::vector<POINT> poly;
    poly.reserve(size_t(trk->n()) * 2 + 1);
    for (int i = 0; i < trk->n(); ++i) {
        POINT p;
        p.x = sx(trk->edge_l[i].x);
        p.y = sy(trk->edge_l[i].y);
        poly.push_back(p);
    }
    for (int i = trk->n() - 1; i >= 0; --i) {
        POINT p;
        p.x = sx(trk->edge_r[i].x);
        p.y = sy(trk->edge_r[i].y);
        poly.push_back(p);
    }
    HBRUSH asfalto = CreateSolidBrush(RGB(46, 50, 58));
    HPEN sem_pena = CreatePen(PS_NULL, 0, RGB(0, 0, 0));
    HGDIOBJ old_b = SelectObject(hdc, asfalto);
    HGDIOBJ old_p = SelectObject(hdc, sem_pena);
    Polygon(hdc, poly.data(), int(poly.size()));
    SelectObject(hdc, old_b);
    SelectObject(hdc, old_p);
    DeleteObject(asfalto);
    DeleteObject(sem_pena);

    // ------------------------------------------------------- bordas
    HPEN borda = CreatePen(PS_SOLID, 2, RGB(228, 232, 240));
    old_p = SelectObject(hdc, borda);
    for (int lado = 0; lado < 2; ++lado) {
        const std::vector<Vec2>& e = lado == 0 ? trk->edge_l : trk->edge_r;
        MoveToEx(hdc, sx(e[0].x), sy(e[0].y), nullptr);
        for (int i = 1; i < trk->n(); ++i) LineTo(hdc, sx(e[i].x), sy(e[i].y));
        if (trk->closed) LineTo(hdc, sx(e[0].x), sy(e[0].y));
    }
    SelectObject(hdc, old_p);
    DeleteObject(borda);

    // ------------------------------------------------------- linha de centro
    HPEN centro = CreatePen(PS_DOT, 1, RGB(90, 96, 108));
    old_p = SelectObject(hdc, centro);
    MoveToEx(hdc, sx(trk->center[0].x), sy(trk->center[0].y), nullptr);
    for (int i = 1; i < trk->n(); ++i) LineTo(hdc, sx(trk->center[i].x), sy(trk->center[i].y));
    if (trk->closed) LineTo(hdc, sx(trk->center[0].x), sy(trk->center[0].y));
    SelectObject(hdc, old_p);
    DeleteObject(centro);

    // ------------------------------------------------------- largada
    int si = trk->start_index % trk->n();
    HPEN largada = CreatePen(PS_SOLID, 3, RGB(240, 240, 240));
    old_p = SelectObject(hdc, largada);
    MoveToEx(hdc, sx(trk->edge_l[si].x), sy(trk->edge_l[si].y), nullptr);
    LineTo(hdc, sx(trk->edge_r[si].x), sy(trk->edge_r[si].y));
    SelectObject(hdc, old_p);
    DeleteObject(largada);

    // ------------------------------------------------------- carros
    std::vector<const Agent*> agentes;
    std::vector<const CarSpec*> specs;
    if (g_app.mode == Mode::Corrida && g_app.race.sim) {
        for (int i = 0; i < g_app.race.sim->n(); ++i) agentes.push_back(&g_app.race.sim->agents[i]);
        specs.assign(agentes.size(), &g_app.car_cache_);
    } else if (g_app.trainer) {
        for (const auto& s : g_app.trainer->shards) {
            for (int i = 0; i < s->n(); ++i) {
                agentes.push_back(&s->agents[i]);
                specs.push_back(&s->specs[i]);
            }
        }
    }
    // foco
    if (g_seguir && !agentes.empty()) {
        const Agent* a = agentes[size_t(g_foco) % agentes.size()];
        g_cam.x = a->car.x;
        g_cam.y = a->car.y;
    }
    const Agent* foco = agentes.empty() ? nullptr : agentes[size_t(g_foco) % agentes.size()];

    for (size_t k = 0; k < agentes.size(); ++k) {
        const Agent* a = agentes[k];
        const CarSpec* sp = specs[k];
        const bool eh_foco = a == foco;
        double comp = sp ? sp->length : 4.0;
        double larg = sp ? sp->width : 1.9;
        double px = std::max(4.0, comp * z);
        double py = std::max(3.0, larg * z);
        double c = std::cos(a->car.heading), s = std::sin(a->car.heading);
        POINT pts[4];
        // referencial do carro: +x para frente, +y para a esquerda
        double canto[4][2] = {{px * 0.5, py * 0.5}, {px * 0.5, -py * 0.5},
                              {-px * 0.5, -py * 0.5}, {-px * 0.5, py * 0.5}};
        for (int i = 0; i < 4; ++i) {
            double wx = a->car.x + canto[i][0] * c - canto[i][1] * s;
            double wy = a->car.y + canto[i][0] * s + canto[i][1] * c;
            pts[i].x = sx(wx);
            pts[i].y = sy(wy);
        }
        COLORREF cor = RGB(224, 72, 58);
        if (eh_foco) cor = RGB(86, 214, 140);
        else if (!a->car.alive) cor = RGB(90, 90, 96);
        else if (g_app.mode == Mode::Corrida && a->car.speed < 0.5) cor = RGB(200, 160, 60);
        HBRUSH b = CreateSolidBrush(cor);
        HPEN p = CreatePen(PS_SOLID, eh_foco ? 2 : 1, eh_foco ? RGB(255, 255, 255) : RGB(30, 30, 34));
        HGDIOBJ ob = SelectObject(hdc, b);
        HGDIOBJ op = SelectObject(hdc, p);
        Polygon(hdc, pts, 4);
        SelectObject(hdc, ob);
        SelectObject(hdc, op);
        DeleteObject(b);
        DeleteObject(p);
    }

    // ------------------------------------------------------- sensores
    if (g_app.ui.mostrar_raios && foco) {
        const int nr = 9;
        std::vector<double> raios(nr);
        trk->cast_rays(Vec2(foco->car.x, foco->car.y), foco->car.heading, foco->idx, nr, 70.0,
                       140.0 * 3.14159265358979 / 180.0, raios.data());
        HPEN raio = CreatePen(PS_SOLID, 1, RGB(120, 200, 255));
        old_p = SelectObject(hdc, raio);
        for (int i = 0; i < nr; ++i) {
            double ang = foco->car.heading + (-70.0 + 140.0 * double(i) / double(nr - 1)) *
                                                 3.14159265358979 / 180.0;
            MoveToEx(hdc, sx(foco->car.x), sy(foco->car.y), nullptr);
            LineTo(hdc, sx(foco->car.x + std::cos(ang) * raios[size_t(i)]),
                   sy(foco->car.y + std::sin(ang) * raios[size_t(i)]));
        }
        SelectObject(hdc, old_p);
        DeleteObject(raio);
    }

    // ------------------------------------------------------- curva de loss
    if (g_app.loss_history.size() >= 2) {
        const int gw = 190, gh = 90;
        int gx = x0 + w - gw - 16, gy = y0 + 16;
        HBRUSH bf = CreateSolidBrush(RGB(20, 24, 32));
        RECT gr = {gx, gy, gx + gw, gy + gh};
        FillRect(hdc, &gr, bf);
        DeleteObject(bf);
        HPEN moldura = CreatePen(PS_SOLID, 1, RGB(70, 78, 92));
        old_p = SelectObject(hdc, moldura);
        Rectangle(hdc, gx, gy, gx + gw, gy + gh);
        double vmax = 0.0;
        for (double v : g_app.loss_history) vmax = std::max(vmax, v);
        vmax = std::max(vmax, 0.5);
        HPEN linha = CreatePen(PS_SOLID, 2, RGB(255, 138, 96));
        SelectObject(hdc, linha);
        const size_t n = g_app.loss_history.size();
        for (size_t i = 0; i < n; ++i) {
            int px = gx + int(double(i) * double(gw - 8) / double(std::max<size_t>(2, n) - 1)) + 4;
            int py = gy + gh - 4 - int(g_app.loss_history[i] / vmax * double(gh - 12));
            if (i == 0) MoveToEx(hdc, px, py, nullptr);
            else LineTo(hdc, px, py);
        }
        SelectObject(hdc, old_p);
        DeleteObject(moldura);
        DeleteObject(linha);
        SetTextColor(hdc, RGB(190, 200, 214));
        SetBkMode(hdc, TRANSPARENT);
        HGDIOBJ of = SelectObject(hdc, g_fonte);
        TextOutW(hdc, gx + 6, gy + 4, L"loss por geração", 16);
        SelectObject(hdc, of);
    }

    // ------------------------------------------------------- HUD
    std::vector<std::string> linhas;
    if (g_app.mode == Mode::Corrida) linhas = g_app.race.hud_lines();
    else linhas = g_app.treino_lines();
    if (g_app.ui.mostrar_hud && !linhas.empty()) {
        SetTextColor(hdc, RGB(232, 236, 244));
        SetBkMode(hdc, TRANSPARENT);
        HGDIOBJ of = SelectObject(hdc, g_fonte_mono);
        int ty = y0 + 16;
        for (const std::string& s : linhas) {
            std::wstring t = wide(s);
            TextOutW(hdc, x0 + 16, ty, t.c_str(), int(t.size()));
            ty += 18;
        }
        SelectObject(hdc, of);
    }
}

// ------------------------------------------------------------------ WndProc
static void mostra_tela() {
    if (g_botao_chave) {
        SetWindowTextW(g_botao_chave, g_app.mode == Mode::Corrida ? L"F2 \u25b8 Treino"
                                                                  : L"F2 \u25b8 Corrida");
    }
    const bool treino = g_app.mode == Mode::Treinamento;
    const bool corrida = g_app.mode == Mode::Corrida;
    // controles de treino
    for (int id : {ID_INICIAR, ID_PAUSAR, ID_REINICIAR, ID_SALVAR, ID_CARREGAR,
                   ID_APLICAR_PY, ID_LIMPAR_PY, ID_EXEMPLO_PY, ID_NOVO,
                   ID_RECOMPENSA_PADRAO}) {
        HWND h = GetDlgItem(g_hwnd, id);
        if (h) ShowWindow(h, treino ? SW_SHOW : SW_HIDE);
    }
    for (Slider& s : g_sliders) {
        if (s.barra) ShowWindow(s.barra, treino ? SW_SHOW : SW_HIDE);
        if (s.texto) ShowWindow(s.texto, treino ? SW_SHOW : SW_HIDE);
    }
    if (g_edita_python) ShowWindow(g_edita_python, treino ? SW_SHOW : SW_HIDE);
    if (g_texto_metricas) ShowWindow(g_texto_metricas, treino ? SW_SHOW : SW_HIDE);
    if (g_texto_corrida) ShowWindow(g_texto_corrida, corrida ? SW_SHOW : SW_HIDE);
    InvalidateRect(g_hwnd, nullptr, TRUE);
}

static void atualiza_textos() {
    if (g_texto_metricas && g_app.mode == Mode::Treinamento) {
        std::vector<std::string> linhas = g_app.treino_lines();
        std::string t;
        for (const std::string& s : linhas) t += s + "\r\n";
        SetWindowTextW(g_texto_metricas, wide(t).c_str());
    }
    if (g_texto_corrida && g_app.mode == Mode::Corrida) {
        std::vector<std::string> linhas = g_app.race.hud_lines();
        std::string t;
        for (const std::string& s : linhas) t += s + "\r\n";
        SetWindowTextW(g_texto_corrida, wide(t).c_str());
    }
}

static void trocar_modo() {
    g_app.alternar_modo();
    mostra_tela();
    atualiza_textos();
}

static void le_teclado() {
    if (g_app.mode != Mode::Corrida) return;
    double steer = 0.0, drive = 0.0;
    if (GetAsyncKeyState(VK_LEFT) & 0x8000) steer += 1.0;
    if (GetAsyncKeyState(VK_RIGHT) & 0x8000) steer -= 1.0;
    if (GetAsyncKeyState('A') & 0x8000) steer += 1.0;
    if (GetAsyncKeyState('D') & 0x8000) steer -= 1.0;
    if (GetAsyncKeyState(VK_UP) & 0x8000) drive += 1.0;
    if (GetAsyncKeyState('W') & 0x8000) drive += 1.0;
    if (GetAsyncKeyState(VK_DOWN) & 0x8000) drive -= 1.0;
    if (GetAsyncKeyState('S') & 0x8000) drive -= 1.0;
    race_set_human(steer, drive);
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
        case WM_CREATE: {
            g_fonte = CreateFontW(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                                  DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                  DEFAULT_QUALITY, DEFAULT_PITCH, L"Segoe UI");
            g_fonte_titulo = CreateFontW(24, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                         DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                                         CLIP_DEFAULT_PRECIS, DEFAULT_QUALITY, DEFAULT_PITCH,
                                         L"Segoe UI");
            g_fonte_mono = CreateFontW(15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                                       DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                       DEFAULT_QUALITY, FIXED_PITCH, L"Consolas");
            const int P = 12;
            const int W = kPainelW - 24;
            rotulo(hwnd, P, 10, W, 26, L"RaceAI 2D — C++", g_fonte_titulo);
            rotulo(hwnd, P, 44, W, 18, L"pista");
            HWND cb_pista = CreateWindowW(L"combobox", L"",
                                          WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
                                          P, 62, W, 200, hwnd, (HMENU)(intptr_t)ID_PISTA,
                                          GetModuleHandle(nullptr), nullptr);
            SendMessageW(cb_pista, WM_SETFONT, (WPARAM)g_fonte, TRUE);
            for (const AssetItem& it : g_app.pistas) {
                SendMessageW(cb_pista, CB_ADDSTRING, 0, (LPARAM)wide(it.name).c_str());
            }
            SendMessageW(cb_pista, CB_SETCURSEL, (WPARAM)g_app.pista_idx, 0);

            rotulo(hwnd, P, 90, W, 18, L"carro");
            HWND cb_carro = CreateWindowW(L"combobox", L"",
                                          WS_CHILD | WS_VISIBLE | CBS_DROPDOWNLIST | WS_VSCROLL,
                                          P, 108, W, 200, hwnd, (HMENU)(intptr_t)ID_CARRO,
                                          GetModuleHandle(nullptr), nullptr);
            SendMessageW(cb_carro, WM_SETFONT, (WPARAM)g_fonte, TRUE);
            for (const AssetItem& it : g_app.carros) {
                SendMessageW(cb_carro, CB_ADDSTRING, 0, (LPARAM)wide(it.name).c_str());
            }
            SendMessageW(cb_carro, CB_SETCURSEL, (WPARAM)g_app.carro_idx, 0);

            botao(hwnd, ID_CORRIDA, P, 140, 120, 30, L"Corrida");
            botao(hwnd, ID_TREINO, P + 128, 140, 120, 30, L"Treinamento");
            g_botao_chave = botao(hwnd, ID_CHAVE_MODO, P + 256, 140, W - 256, 30, L"F2 ▸ Treino");

            // ---- treino: configuração
            int y = 180;
            cria_slider(hwnd, P, y, 180, L"indivíduos",
                        &g_app.train_cfg.individuals, 10, 300, 1);
            cria_slider(hwnd, P + 196, y, 180, L"gerações",
                        &g_app.train_cfg.generations, 5, 1000, 1);
            y += 46;
            cria_slider(hwnd, P, y, 180, L"segundos/episódio",
                        &g_app.train_cfg.seconds, 10, 180, 1);
            cria_slider(hwnd, P + 196, y, 180, L"voltas alvo",
                        &g_app.train_cfg.laps, 0, 10, 1);
            y += 46;
            cria_slider(hwnd, P, y, 180, L"velocidade da sim",
                        &g_app.ui.velocidade_sim, 1, 16, 1);
            cria_slider(hwnd, P + 196, y, 180, L"neurônios",
                        &g_app.train_cfg.hidden, 16, 128, 1);

            // ---- recompensa (os sliders pedidos)
            y += 52;
            rotulo(hwnd, P, y, W, 18, L"recompensa (o que a IA ganha)", g_fonte);
            y += 20;
            cria_slider(hwnd, P, y, 180, L"progresso", &g_app.reward.progress, 0, 3, 100);
            cria_slider(hwnd, P + 196, y, 180, L"velocidade", &g_app.reward.speed, 0, 3, 100);
            y += 40;
            cria_slider(hwnd, P, y, 180, L"precisão", &g_app.reward.precision, 0, 3, 100);
            cria_slider(hwnd, P + 196, y, 180, L"suavidade", &g_app.reward.smooth, 0, 3, 100);
            y += 46;
            rotulo(hwnd, P, y, W, 18, L"penalidades (o que a IA perde)", g_fonte);
            y += 20;
            cria_slider(hwnd, P, y, 180, L"fora da pista", &g_app.reward.offtrack, 0, 3, 100);
            cria_slider(hwnd, P + 196, y, 180, L"batida", &g_app.reward.crash, 0, 3, 100);
            y += 40;
            cria_slider(hwnd, P, y, 180, L"contra-mão", &g_app.reward.wrongway, 0, 3, 100);
            cria_slider(hwnd, P + 196, y, 180, L"parado/desistir", &g_app.reward.idle, 0, 3, 100);
            y += 40;
            cria_slider(hwnd, P, y, 180, L"bônus de conclusão", &g_app.reward.finish_bonus,
                        0, 100, 10);
            cria_slider(hwnd, P + 196, y, 180, L"velocidade de referência",
                        &g_app.reward.ref_speed_factor, 0.1, 1.0, 100);
            y += 46;
            botao(hwnd, ID_RECOMPENSA_PADRAO, P, y, W, 26, L"voltar aos pesos padrão");

            // ---- botões do treino
            y += 36;
            botao(hwnd, ID_INICIAR, P, y, 118, 30, L"Iniciar");
            botao(hwnd, ID_PAUSAR, P + 126, y, 118, 30, L"Pausar");
            botao(hwnd, ID_REINICIAR, P + 252, y, 132, 30, L"Zerar tudo");
            y += 36;
            botao(hwnd, ID_SALVAR, P, y, 180, 26, L"Salvar modelo");
            botao(hwnd, ID_CARREGAR, P + 188, y, 196, 26, L"Carregar modelo");

            // ---- IA em Python
            y += 36;
            rotulo(hwnd, P, y, W, 18, L"sua IA em Python: dirigir(sensores)", g_fonte);
            y += 20;
            g_edita_python = CreateWindowExW(WS_EX_CLIENTEDGE, L"edit", L"",
                                             WS_CHILD | WS_VISIBLE | ES_MULTILINE |
                                                 ES_WANTRETURN | ES_AUTOVSCROLL | WS_VSCROLL |
                                                 WS_HSCROLL,
                                             P, y, W, 190, hwnd, nullptr,
                                             GetModuleHandle(nullptr), nullptr);
            SendMessageW(g_edita_python, WM_SETFONT, (WPARAM)g_fonte_mono, TRUE);
            SetWindowTextW(g_edita_python, wide(g_app.python_code).c_str());
            y += 196;
            botao(hwnd, ID_APLICAR_PY, P, y, 130, 26, L"Aplicar código");
            botao(hwnd, ID_EXEMPLO_PY, P + 136, y, 112, 26, L"Exemplo");
            botao(hwnd, ID_ABRIR_PY, P + 254, y, 118, 26, L"Abrir .py");
            botao(hwnd, ID_SALVAR_PY, P + 378, y, 118, 26, L"Salvar .py");
            botao(hwnd, ID_LIMPAR_PY, P + 502, y, 100, 26, L"Limpar");

            y += 32;
            g_texto_metricas = CreateWindowW(L"edit", L"",
                                             WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_READONLY |
                                                 WS_VSCROLL,
                                             P, y, W, 150, hwnd, nullptr,
                                             GetModuleHandle(nullptr), nullptr);
            SendMessageW(g_texto_metricas, WM_SETFONT, (WPARAM)g_fonte_mono, TRUE);

            // ---- corrida
            g_texto_corrida = CreateWindowW(L"edit", L"",
                                            WS_CHILD | ES_MULTILINE | ES_READONLY | WS_VSCROLL,
                                            P, 180, W, 300, hwnd, nullptr,
                                            GetModuleHandle(nullptr), nullptr);
            SendMessageW(g_texto_corrida, WM_SETFONT, (WPARAM)g_fonte_mono, TRUE);
            botao(hwnd, ID_REINICIAR, P, 490, 130, 28, L"Reiniciar");
            botao(hwnd, ID_ADD_MODELO, P + 138, 490, 150, 28, L"Adicionar modelo");
            botao(hwnd, ID_MENU, P, 526, 180, 28, L"Voltar ao menu");

            rotulo(hwnd, P, 570, W, 130,
                   L"Setas/WASD dirigem\nF2 alterna Corrida/Treino\n"
                   L"R reinicia a corrida\nC troca a câmera\n"
                   L"+/- aproxima\nH mostra/esconde o HUD\nESC volta ao menu");

            mostra_tela();
            SetTimer(hwnd, kTimer, 16, nullptr);
            return 0;
        }
        case WM_TIMER: {
            le_teclado();
            const int passos = std::max(1, int(g_app.ui.velocidade_sim * 2));
            if (g_app.mode == Mode::Treinamento) g_app.tick_treino(passos);
            else if (g_app.mode == Mode::Corrida) g_app.tick_corrida(passos);
            atualiza_textos();
            InvalidateRect(hwnd, nullptr, FALSE);
            return 0;
        }
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            RECT rc;
            GetClientRect(hwnd, &rc);
            // painel
            HBRUSH pincel = CreateSolidBrush(RGB(24, 28, 36));
            RECT pr = {0, 0, kPainelW, rc.bottom};
            FillRect(hdc, &pr, pincel);
            DeleteObject(pincel);
            HPEN linha = CreatePen(PS_SOLID, 1, RGB(48, 54, 66));
            HGDIOBJ op = SelectObject(hdc, linha);
            MoveToEx(hdc, kPainelW, 0, nullptr);
            LineTo(hdc, kPainelW, rc.bottom);
            SelectObject(hdc, op);
            DeleteObject(linha);
            pinta_canvas(hdc, kPainelW + 1, 0, std::max(1, int(rc.right) - kPainelW - 1), int(rc.bottom));
            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_HSCROLL: {
            for (Slider& s : g_sliders) {
                if (s.barra == (HWND)lp && s.valor) {
                    int pos = int(SendMessageW(s.barra, TBM_GETPOS, 0, 0));
                    *s.valor = double(pos) / s.escala;
                    s.atualiza();
                    g_app.aplicar_recompensa(g_app.reward);
                    g_app.aplicar_treino_cfg(g_app.train_cfg);
                    break;
                }
            }
            return 0;
        }
        case WM_GETMINMAXINFO: {
            // nunca deixa a janela ficar pequena a ponto de cortar o painel
            MINMAXINFO* mm = (MINMAXINFO*)lp;
            mm->ptMinTrackSize.x = 900;
            mm->ptMinTrackSize.y = 560;
            return 0;
        }
        case WM_COMMAND: {
            const int id = LOWORD(wp);
            if (id == ID_PISTA && HIWORD(wp) == CBN_SELCHANGE) {
                int i = int(SendMessageW((HWND)lp, CB_GETCURSEL, 0, 0));
                if (g_app.carregar_pista(i) && g_app.trainer) {
                    g_app.trainer->set_track(g_app.track_cache_);
                }
                g_foco = 0;
            } else if (id == ID_CARRO && HIWORD(wp) == CBN_SELCHANGE) {
                int i = int(SendMessageW((HWND)lp, CB_GETCURSEL, 0, 0));
                g_app.carregar_carro(i);
            } else if (id == ID_CHAVE_MODO) {
                trocar_modo();
            } else if (id == ID_TREINO) {
                g_app.mode = Mode::Treinamento;
                mostra_tela();
            } else if (id == ID_CORRIDA) {
                g_app.iniciar_corrida({});
                mostra_tela();
            } else if (id == ID_MENU || id == ID_VOLTAR) {
                g_app.mode = Mode::Menu;
                mostra_tela();
            } else if (id == ID_INICIAR) {
                g_app.iniciar_treino(!g_app.trainer);
            } else if (id == ID_PAUSAR) {
                g_app.ui.pausado = !g_app.ui.pausado;
            } else if (id == ID_REINICIAR) {
                if (g_app.mode == Mode::Corrida) g_app.race.restart();
                else g_app.iniciar_treino(true);
            } else if (id == ID_NOVO) {
                g_app.iniciar_treino(true);
            } else if (id == ID_APLICAR_PY) {
                wchar_t buf[65536];
                GetWindowTextW(g_edita_python, buf, 65535);
                std::string codigo = narrow(buf);
                if (g_app.aplicar_codigo_python(codigo)) {
                    MessageBoxW(hwnd, wide("Código aplicado. A IA em Python assume o carro 0 "
                                           "(o de foco) no treino e na corrida.").c_str(),
                                L"IA em Python", MB_OK | MB_ICONINFORMATION);
                } else {
                    MessageBoxW(hwnd, wide(g_app.python_status).c_str(), L"Erro no código",
                                MB_OK | MB_ICONERROR);
                }
            } else if (id == ID_ABRIR_PY || id == ID_SALVAR_PY) {
                wchar_t arquivo[MAX_PATH] = L"minha_ia.py";
                OPENFILENAMEW ofn = {};
                ofn.lStructSize = sizeof(ofn);
                ofn.hwndOwner = hwnd;
                ofn.lpstrFile = arquivo;
                ofn.nMaxFile = MAX_PATH;
                ofn.lpstrFilter = L"Python\0*.py\0Todos\0*.*\0";
                ofn.nFilterIndex = 1;
                ofn.Flags = OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_OVERWRITEPROMPT;
                ofn.lpstrDefExt = L"py";
                if (id == ID_ABRIR_PY) {
                    ofn.Flags = OFN_PATHMUSTEXIST | OFN_FILEMUSTEXIST | OFN_HIDEREADONLY;
                    if (GetOpenFileNameW(&ofn)) {
                        std::string err;
                        std::string caminho = narrow(arquivo);
                        if (g_app.importar_python(caminho, &err)) {
                            SetWindowTextW(g_edita_python, wide(g_app.python_code).c_str());
                            MessageBoxW(hwnd,
                                        wide("Arquivo carregado e aplicado:\n" + caminho).c_str(),
                                        L"IA em Python", MB_OK | MB_ICONINFORMATION);
                        } else {
                            MessageBoxW(hwnd, wide(err).c_str(), L"Erro ao abrir .py",
                                        MB_OK | MB_ICONERROR);
                        }
                    }
                } else {
                    if (GetSaveFileNameW(&ofn)) {
                        wchar_t buf[65536];
                        GetWindowTextW(g_edita_python, buf, 65535);
                        g_app.aplicar_codigo_python(narrow(buf));   // guarda o que está na tela
                        std::string err;
                        if (g_app.salvar_python(narrow(arquivo), &err)) {
                            MessageBoxW(hwnd, wide("Código salvo em:\n" + narrow(arquivo)).c_str(),
                                        L"IA em Python", MB_OK | MB_ICONINFORMATION);
                        } else {
                            MessageBoxW(hwnd, wide(err).c_str(), L"Erro ao salvar .py",
                                        MB_OK | MB_ICONERROR);
                        }
                    }
                }
            } else if (id == ID_EXEMPLO_PY) {
                SetWindowTextW(g_edita_python, wide(exemplo_python()).c_str());
            } else if (id == ID_LIMPAR_PY) {
                SetWindowTextW(g_edita_python, L"");
                g_app.python_enabled = false;
            } else if (id == ID_RECOMPENSA_PADRAO) {
                RewardConfig r;
                g_app.aplicar_recompensa(r);
                for (Slider& s : g_sliders) s.atualiza();
            } else if (id == ID_SALVAR || id == ID_CARREGAR) {
                wchar_t arquivo[MAX_PATH] = L"modelo.raceai.json";
                OPENFILENAMEW ofn;
                ZeroMemory(&ofn, sizeof(ofn));
                ofn.lStructSize = sizeof(ofn);
                ofn.hwndOwner = hwnd;
                ofn.lpstrFile = arquivo;
                ofn.nMaxFile = MAX_PATH;
                ofn.lpstrFilter = L"Rede neural (qualquer formato)\0*.json;*.pt;*.pth;*.npz;*.safetensors\0Modelo do jogo\0*.json\0PyTorch\0*.pt;*.pth\0NumPy\0*.npz\0safetensors\0*.safetensors\0Todos\0*.*\0";
                ofn.Flags = OFN_OVERWRITEPROMPT;
                std::string err;
                if (id == ID_SALVAR && GetSaveFileNameW(&ofn)) {
                    if (!g_app.salvar_modelo(narrow(arquivo), &err)) {
                        MessageBoxW(hwnd, wide(err).c_str(), L"Erro", MB_OK | MB_ICONERROR);
                    }
                } else if (id == ID_CARREGAR && GetOpenFileNameW(&ofn)) {
                    if (!g_app.carregar_modelo(narrow(arquivo), &err)) {
                        MessageBoxW(hwnd, wide(err).c_str(), L"Erro", MB_OK | MB_ICONERROR);
                    } else {
                        g_app.mode = Mode::Treinamento;
                        mostra_tela();
                    }
                }
            } else if (id == ID_ADD_MODELO) {
                wchar_t arquivo[MAX_PATH] = L"";
                OPENFILENAMEW ofn;
                ZeroMemory(&ofn, sizeof(ofn));
                ofn.lStructSize = sizeof(ofn);
                ofn.hwndOwner = hwnd;
                ofn.lpstrFile = arquivo;
                ofn.nMaxFile = MAX_PATH;
                ofn.lpstrFilter = L"Rede neural (qualquer formato)\0*.json;*.pt;*.pth;*.npz;*.safetensors\0Modelo do jogo\0*.json\0PyTorch\0*.pt;*.pth\0NumPy\0*.npz\0safetensors\0*.safetensors\0Todos\0*.*\0";
                ofn.Flags = OFN_FILEMUSTEXIST;
                if (GetOpenFileNameW(&ofn)) {
                    g_app.iniciar_corrida({narrow(arquivo)});
                    mostra_tela();
                }
            } else if (id == ID_AJUDA) {
                MessageBoxW(hwnd, wide(ajuda_python()).c_str(), L"Ajuda — IA em Python", MB_OK);
            }
            return 0;
        }
        case WM_KEYDOWN: {
            if (wp == VK_F2) {
                trocar_modo();
            } else if (wp == VK_ESCAPE) {
                g_app.mode = Mode::Menu;
                mostra_tela();
            } else if (wp == 'R') {
                if (g_app.mode == Mode::Corrida) g_app.race.restart();
                else g_app.iniciar_treino(true);
            } else if (wp == 'C') {
                g_seguir = !g_seguir;
            } else if (wp == 'H') {
                g_app.ui.mostrar_hud = !g_app.ui.mostrar_hud;
            } else if (wp == 'O') {
                g_app.ui.mostrar_raios = !g_app.ui.mostrar_raios;
            } else if (wp == VK_OEM_PLUS || wp == VK_ADD) {
                g_zoom = std::min(40.0, g_zoom * 1.2);
                g_cam.z = g_zoom;
            } else if (wp == VK_OEM_MINUS || wp == VK_SUBTRACT) {
                g_zoom = std::max(1.0, g_zoom / 1.2);
                g_cam.z = g_zoom;
            } else if (wp == VK_TAB) {
                g_foco += 1;
            } else if (wp == 'P') {
                g_app.ui.pausado = !g_app.ui.pausado;
            }
            return 0;
        }
        case WM_MOUSEWHEEL: {
            double delta = GET_WHEEL_DELTA_WPARAM(wp) > 0 ? 1.2 : 1.0 / 1.2;
            g_zoom = std::max(1.0, std::min(40.0, g_zoom * delta));
            g_cam.z = g_zoom;
            InvalidateRect(hwnd, nullptr, FALSE);
            return 0;
        }
        case WM_ERASEBKGND:
            return 1;
        case WM_DESTROY:
            KillTimer(hwnd, kTimer);
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// ------------------------------------------------------------------ main
// ------------------------------------------------------------------ log/erro
// Um .exe de interface nao tem console: se algo estoura na inicializacao o
// processo simplesmente some. Entao todo erro vai para raceai.log (ao lado do
// .exe) e para uma mensagem na tela.
static std::wstring g_dir_app = L".";

static void log_linha(const std::wstring& txt) {
    std::ofstream f(narrow(g_dir_app + L"\\raceai.log"), std::ios::app);
    if (!f) return;
    f << narrow(txt) << "\n";
}
static void log_erro(const std::wstring& onde, const std::wstring& det) {
    log_linha(L"[ERRO] " + onde + L": " + det);
    MessageBoxW(nullptr, (onde + L"\n\n" + det + L"\n\nDetalhes em raceai.log").c_str(),
                L"RaceAI 2D", MB_OK | MB_ICONERROR);
}

static std::wstring mensagem_win32(DWORD cod) {
    wchar_t* buf = nullptr;
    DWORD n = FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                                 FORMAT_MESSAGE_IGNORE_INSERTS,
                             nullptr, cod, 0, (LPWSTR)&buf, 0, nullptr);
    std::wstring s = (n && buf) ? std::wstring(buf, n) : std::wstring(L"erro " + std::to_wstring(cod));
    if (buf) LocalFree(buf);
    while (!s.empty() && (s.back() == L'\n' || s.back() == L'\r')) s.pop_back();
    return s;
}

static int rodar(HINSTANCE hInst, int cmd_show) {
    wchar_t modulo[MAX_PATH];
    GetModuleFileNameW(nullptr, modulo, MAX_PATH);
    std::wstring caminho = modulo;
    size_t barra = caminho.find_last_of(L"\\/");
    g_dir_app = (barra == std::wstring::npos) ? L"." : caminho.substr(0, barra);

    // tudo (pistas, carros, saves) é resolvido a partir da pasta do .exe,
    // não da pasta de onde ele foi chamado
    SetCurrentDirectoryW(g_dir_app.c_str());

    // Python (opcional): se a pasta python/ nao existir, o app segue em C++
    std::wstring pyhome = g_dir_app + L"\\python";
    DWORD py_attr = GetFileAttributesW(pyhome.c_str());
    if (py_attr != INVALID_FILE_ATTRIBUTES && (py_attr & FILE_ATTRIBUTE_DIRECTORY)) {
        SetEnvironmentVariableW(L"PYTHONHOME", pyhome.c_str());
        std::wstring pycaminho = pyhome + L"\\python311.zip;" + pyhome + L";" + g_dir_app;
        SetEnvironmentVariableW(L"PYTHONPATH", pycaminho.c_str());
        log_linha(L"python: " + pyhome);
    } else {
        SetEnvironmentVariableW(L"PYTHONHOME", nullptr);
        SetEnvironmentVariableW(L"PYTHONPATH", nullptr);
        log_linha(L"python: ausente (modo C++ puro)");
    }

    INITCOMMONCONTROLSEX icc;
    icc.dwSize = sizeof(icc);
    icc.dwICC = ICC_BAR_CLASSES | ICC_WIN95_CLASSES | ICC_STANDARD_CLASSES;
    InitCommonControlsEx(&icc);

    WNDCLASSEXW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = kClasse;
    if (!RegisterClassExW(&wc)) {
        log_erro(L"RegisterClassExW", mensagem_win32(GetLastError()));
        return 1;
    }

    // tamanho: cabe na tela do usuario (1366x768, 1024x600 etc.)
    RECT area = {0, 0, 0, 0};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &area, 0);
    int disp_w = area.right - area.left, disp_h = area.bottom - area.top;
    if (disp_w < 320 || disp_h < 240) { disp_w = 1360; disp_h = 768; }
    int larg = std::min(1360, disp_w - 20);
    int alt = std::min(900, disp_h - 20);
    larg = std::max(larg, 900);
    alt = std::max(alt, 560);

    g_hwnd = CreateWindowExW(0, kClasse, L"RaceAI 2D — treino de IA (C++)",
                             WS_OVERLAPPEDWINDOW, area.left + std::max(0, (disp_w - larg) / 2),
                             area.top + std::max(0, (disp_h - alt) / 2), larg, alt, nullptr,
                             nullptr, hInst, nullptr);
    if (!g_hwnd) {
        log_erro(L"CreateWindowExW", mensagem_win32(GetLastError()));
        return 1;
    }
    ShowWindow(g_hwnd, cmd_show);
    UpdateWindow(g_hwnd);
    log_linha(L"[OK] janela criada " + std::to_wstring(larg) + L"x" + std::to_wstring(alt));

    MSG msg;
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return int(msg.wParam);
}

int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int cmd_show) {
    // caminho do log ainda nao conhecido: usa o do proprio executavel
    {
        wchar_t modulo[MAX_PATH];
        GetModuleFileNameW(nullptr, modulo, MAX_PATH);
        std::wstring c = modulo;
        size_t b = c.find_last_of(L"\\/");
        g_dir_app = (b == std::wstring::npos) ? L"." : c.substr(0, b);
    }
    log_linha(L"=== RaceAI 2D iniciando ===");
    int rc = 0;
    try {
        rc = rodar(hInst, cmd_show);
    } catch (const std::exception& e) {
        log_erro(L"excecao nao tratada", wide(e.what() ? e.what() : "?"));
        rc = 2;
    } catch (...) {
        log_erro(L"excecao nao tratada", L"(tipo desconhecido)");
        rc = 3;
    }
    log_linha(L"=== fim (rc=" + std::to_wstring(rc) + L") ===");
    return rc;
}

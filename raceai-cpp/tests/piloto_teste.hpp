// piloto_teste.hpp — o "piloto automático" usado pelos testes.
//
// É o mesmo motorista nos dois lugares (testes do núcleo e de integração):
// perseguição pura com velocidade-alvo pela curvatura. Se a física muda, o
// acerto só precisa ser feito uma vez — e os dois testes continuam provando a
// mesma coisa: que toda pista e todo carro entregues são dirigíveis de verdade.
#pragma once

#include "../src/core/sim.hpp"

namespace raceai {

struct AcaoTeste {
    double esterco = 0.0;
    double acelerador = 0.0;
};

inline AcaoTeste piloto_teste(const Agent& a, const Track& t, const CarSpec& c) {
    const int n = t.n();
    const int frente = std::max(3, int((6.0 + a.car.speed * 0.55) / std::max(t.spacing, 0.5)));
    const Vec2 alvo = t.center[(a.idx + frente) % n];
    double desejado = std::atan2(alvo.y - a.car.y, alvo.x - a.car.x);
    double erro = desejado - a.car.heading;
    while (erro > kPi) erro -= 2 * kPi;
    while (erro < -kPi) erro += 2 * kPi;

    // termo derivativo na taxa de guinada: sem isso os carros potentes
    // (monoposto, GT) entram em oscilação e batem
    double cs = (std::fabs(a.car.slip_r) > 0.30) ? 0.45 * a.car.slip_r : 0.06 * a.car.slip_r;
    double steer = std::max(-1.0, std::min(1.0, 1.1 * erro - 0.40 * a.car.r - cs));

    // curvatura à frente -> velocidade alvo (margem de segurança: a física
    // real entrega menos do que mu * peso por causa da transferência de carga)
    const int la = std::max(6, frente * 2);
    const Vec2& tan_a = t.tangents[a.idx];
    const Vec2& tan_b = t.tangents[(a.idx + la) % n];
    double curv = std::fabs(std::atan2(tan_b.y, tan_b.x) - std::atan2(tan_a.y, tan_a.x));
    if (curv > kPi) curv = 2 * kPi - curv;
    const double raio = std::max(8.0, la * t.spacing / std::max(curv, 0.05));
    const double mu = 0.45 * (c.grip_front + c.grip_rear) * 0.5;
    const double v_alvo = std::min(c.max_speed * 0.75, std::sqrt(mu * 9.81 * raio));

    // frear com o volante virado derruba o carro: dosa o freio pelo esterço
    const double ganho_freio = 1.0 - 0.55 * std::min(1.0, std::fabs(steer));
    double drive = a.car.speed < v_alvo ? 1.0
                 : (a.car.speed > v_alvo * 1.25 ? -0.9 * ganho_freio
                                                 : -0.35 * ganho_freio);
    // traseira saindo: alivia o freio antes de rodar de vez
    if (std::fabs(a.car.slip_r) > 0.45) drive = std::max(drive, -0.15);
    // roda patinando: o pé levanta, igual a um piloto de verdade
    if (drive > 0.0 && a.car.wheelspin > 0.10) drive = std::min(drive, 0.30);
    // rodou: reduz e contra-esterça até apontar de novo para frente
    if (std::fabs(erro) > 2.0) {
        drive = a.car.speed > 4.0 ? -0.5 : 0.35;
        steer = erro > 0.0 ? 1.0 : -1.0;
    }
    return AcaoTeste{steer, drive};
}

}  // namespace raceai

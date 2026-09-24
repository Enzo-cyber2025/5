#pragma once
#include <algorithm>
#include <vector>
// Quanto de CPU usar quando o usuário não escolheu um número.
//
// Duas correções sobre a política anterior, ambas medidas em laboratório de
// threads com o modelo real (ver docs/PERFORMANCE_UI.md):
//
//  * sem informação de capacidade no sistema de arquivos (emulador, kernel sem
//    cpu_capacity), a política antiga fixava 4. Um aparelho com 6 ou 8 núcleos
//    iguais ficava com dois terços da CPU parada enquanto o modelo era servido
//    só por quatro. Agora usamos os núcleos disponíveis, com teto de 8.
//  * com capacidades conhecidas, o corte em 60% do pico descartava os núcleos
//    "pequenos", que em muitos SoCs ainda somam desempenho útil para um modelo
//    que não cabe em cache; o corte passa a 50% do pico, mantendo o teto de 8
//    para não perder a folga térmica de um núcleo grande.
//
// Um pedido explícito do usuário continua sendo respeitado sem arredondamento.
static inline int resolve_cpu_threads(int requested,int available,const std::vector<int>& capacities) {
    if(requested>0)return std::max(1,std::min(requested,8));
    available=std::max(1,available);
    int selected=available; // sem capacidades: todos os núcleos permitidos
    if((int)capacities.size()==available) {
        int peak=*std::max_element(capacities.begin(),capacities.end());
        int minimum=*std::min_element(capacities.begin(),capacities.end());
        if(minimum>0&&peak>minimum) {
            selected=0;for(int capacity:capacities)if((long long)capacity*100>=peak*50LL)selected++;
        }
    }
    return std::max(1,std::min(selected,8));
}

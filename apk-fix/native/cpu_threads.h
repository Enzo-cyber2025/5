#pragma once
#include <algorithm>
#include <vector>
// Politica de threads: em SoCs big.LITTLE (Exynos 1480 do A55, Snapdragon 7 Gen 3 etc),
// os big cores geram 70-85% dos tokens/s; os LITTLE ajudam no prefill mas roubam banda e
// causam thermal throttling no decode longo. Selecionamos nucleos com capacidade >= 60%
// do pico (pega 1+3 big/mid no A55), teto 8 para 8-core phones.
static inline int resolve_cpu_threads(int requested,int available,const std::vector<int>& capacities) {
    if(requested>0)return std::max(1,std::min(requested,8));
    available=std::max(1,available);
    int selected=available;
    if((int)capacities.size()==available) {
        int peak=*std::max_element(capacities.begin(),capacities.end());
        int minimum=*std::min_element(capacities.begin(),capacities.end());
        if(minimum>0&&peak>minimum) {
            selected=0;for(int capacity:capacities)if((long long)capacity*100>=peak*60LL)selected++;
            // Se todos forem >=60% (desktop/emulador), usa todos ate o teto.
            // Se nenhum passar de 60% (capacidade uniforme), cai pra todos.
            if(selected==0)selected=available;
        }
    }
    return std::max(1,std::min(selected,8));
}
// Mascara de CPU com os N nucleos de maior capacidade (para pin do decode).
static inline std::vector<int> pick_top_cores(const std::vector<int>& capacities,int want) {
    std::vector<std::pair<int,int>> v; // (capacity, cpu)
    for(int i=0;i<(int)capacities.size();i++)v.emplace_back(capacities[i],i);
    std::sort(v.rbegin(),v.rend());
    std::vector<int> out;
    for(int i=0;i<std::min(want,(int)v.size());i++)if(v[i].first>0)out.push_back(v[i].second);
    return out;
}

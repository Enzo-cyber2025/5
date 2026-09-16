#pragma once
#include <algorithm>
#include <vector>
static inline int resolve_cpu_threads(int requested,int available,const std::vector<int>& capacities) {
    if(requested>0)return std::max(1,std::min(requested,8));
    available=std::max(1,available);
    int selected=std::min(4,available); // conservative mobile fallback, NOT one thread
    if((int)capacities.size()==available) {
        int peak=*std::max_element(capacities.begin(),capacities.end());
        int minimum=*std::min_element(capacities.begin(),capacities.end());
        if(minimum>0&&peak>minimum) {
            // Include big + middle cores, not only a single prime core.
            selected=0;for(int capacity:capacities)if((long long)capacity*100>=peak*60LL)selected++;
        }
    }
    return std::max(1,std::min(selected,8));
}

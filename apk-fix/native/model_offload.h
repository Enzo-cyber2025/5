#pragma once
// A missing/partial loader report is not proof of a fully offloaded model.
// Runtime graph guards remain authoritative for every tensor math operation.
inline bool complete_gpu_offload(int loaded,int total) {
    return total>0 && loaded==total;
}

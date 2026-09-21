// Real host capability query without vulkaninfo's unrelated WSI/surface probes.
#include <vulkan/vulkan.h>
#include <cstdio>
#include <vector>
int main() {
    VkApplicationInfo app{}; app.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO; app.apiVersion=VK_API_VERSION_1_1;
    VkInstanceCreateInfo info{}; info.sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO; info.pApplicationInfo=&app;
    VkInstance instance=VK_NULL_HANDLE;
    VkResult result=vkCreateInstance(&info,nullptr,&instance);
    if(result!=VK_SUCCESS){std::fprintf(stderr,"vkCreateInstance failed: %d\n",result);return 1;}
    uint32_t count=0;result=vkEnumeratePhysicalDevices(instance,&count,nullptr);
    if(result!=VK_SUCCESS || count!=1){std::fprintf(stderr,"Expected pinned Lavapipe ICD with one physical device: %u\n",count);vkDestroyInstance(instance,nullptr);return 1;}
    std::vector<VkPhysicalDevice> devices(count);result=vkEnumeratePhysicalDevices(instance,&count,devices.data());
    if(result!=VK_SUCCESS){vkDestroyInstance(instance,nullptr);return 1;}
    VkPhysicalDevice16BitStorageFeatures storage{};storage.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_16BIT_STORAGE_FEATURES;
    VkPhysicalDeviceShaderFloat16Int8Features f16i8{};
    f16i8.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_FLOAT16_INT8_FEATURES;
    storage.pNext=&f16i8;
    VkPhysicalDeviceSubgroupSizeControlFeatures subgroup_control{};
    subgroup_control.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_FEATURES;
    f16i8.pNext=&subgroup_control;
    VkPhysicalDeviceShaderIntegerDotProductFeatures dot_features{};
    dot_features.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_INTEGER_DOT_PRODUCT_FEATURES;
    subgroup_control.pNext=&dot_features;
    VkPhysicalDeviceFeatures2 features{};features.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;features.pNext=&storage;
    vkGetPhysicalDeviceFeatures2(devices[0],&features);
    VkPhysicalDeviceProperties properties{};vkGetPhysicalDeviceProperties(devices[0],&properties);

    // Subgroup shape decides whether the pinned matvec can reduce inside registers
    // (subgroupAdd) or has to go through shared memory with one barrier per level.
    VkPhysicalDeviceSubgroupProperties subgroup{};
    subgroup.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_PROPERTIES;
    VkPhysicalDeviceSubgroupSizeControlProperties size_control{};
    size_control.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_SIZE_CONTROL_PROPERTIES;
    subgroup.pNext=&size_control;
    VkPhysicalDeviceShaderIntegerDotProductProperties dot_props{};
    dot_props.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_INTEGER_DOT_PRODUCT_PROPERTIES;
    size_control.pNext=&dot_props;
    VkPhysicalDeviceProperties2 properties2{};properties2.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;properties2.pNext=&subgroup;
    vkGetPhysicalDeviceProperties2(devices[0],&properties2);

    std::printf("Queried device: %s\nstorageBuffer16BitAccess = %s\n",
                properties.deviceName,storage.storageBuffer16BitAccess?"true":"false");
    std::printf("shaderFloat16 = %s\nshaderInt8 = %s\n",
                f16i8.shaderFloat16?"true":"false",f16i8.shaderInt8?"true":"false");
    std::printf("subgroupSize = %u\nsubgroupSupportedStages = 0x%x\nsubgroupSupportedOperations = 0x%x\n"
                "subgroupQuadOperationsInAllStages = %s\n"
                "subgroupArithmetic = %s\nsubgroupShuffle = %s\nsubgroupClustered = %s\nsubgroupBallot = %s\n",
                subgroup.subgroupSize,subgroup.supportedStages,subgroup.supportedOperations,
                subgroup.quadOperationsInAllStages?"true":"false",
                (subgroup.supportedOperations & VK_SUBGROUP_FEATURE_ARITHMETIC_BIT)?"true":"false",
                (subgroup.supportedOperations & VK_SUBGROUP_FEATURE_SHUFFLE_BIT)?"true":"false",
                (subgroup.supportedOperations & VK_SUBGROUP_FEATURE_CLUSTERED_BIT)?"true":"false",
                (subgroup.supportedOperations & VK_SUBGROUP_FEATURE_BALLOT_BIT)?"true":"false");
    std::printf("subgroupSizeControl = %s\ncomputeFullSubgroups = %s\nminSubgroupSize = %u\nmaxSubgroupSize = %u\n"
                "shaderIntegerDotProduct = %s\n",
                subgroup_control.subgroupSizeControl?"true":"false",
                subgroup_control.computeFullSubgroups?"true":"false",
                size_control.minSubgroupSize,size_control.maxSubgroupSize,
                dot_features.shaderIntegerDotProduct?"true":"false");
    std::printf("maxComputeWorkGroupInvocations = %u\nmaxComputeWorkGroupSize = (%u,%u,%u)\n"
                "maxComputeWorkGroupCount = (%u,%u,%u)\ntimestampPeriod = %.3f\n",
                properties.limits.maxComputeWorkGroupInvocations,
                properties.limits.maxComputeWorkGroupSize[0],properties.limits.maxComputeWorkGroupSize[1],properties.limits.maxComputeWorkGroupSize[2],
                properties.limits.maxComputeWorkGroupCount[0],properties.limits.maxComputeWorkGroupCount[1],properties.limits.maxComputeWorkGroupCount[2],
                (double)properties.limits.timestampPeriod);
    vkDestroyInstance(instance,nullptr);
    return storage.storageBuffer16BitAccess?0:1;
}

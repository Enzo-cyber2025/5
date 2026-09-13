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
    VkPhysicalDeviceFeatures2 features{};features.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;features.pNext=&storage;
    vkGetPhysicalDeviceFeatures2(devices[0],&features);
    VkPhysicalDeviceProperties properties{};vkGetPhysicalDeviceProperties(devices[0],&properties);
    std::printf("Queried device: %s\nstorageBuffer16BitAccess = %s\n",properties.deviceName,storage.storageBuffer16BitAccess?"true":"false");
    vkDestroyInstance(instance,nullptr);
    return storage.storageBuffer16BitAccess?0:1;
}

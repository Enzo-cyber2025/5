// llvmpipe compute ceiling probe (disposable CI runner only).
//
// Usage: ceiling --spv <file.spv> --block <n> --groups <n> --inner <n> --reps <n>
// Prints one CSV line with the measured time and effective GFLOPS. The pattern is
// chosen at shader build time (glslc -D PATTERN=...); this program only sets the
// workgroup size specialization constant, the grid and the inner loop count.
#include <vulkan/vulkan.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#define VKC(expr) do { VkResult _r = (expr); if (_r != VK_SUCCESS) { \
    std::fprintf(stderr, "%s failed: %d\n", #expr, (int) _r); std::exit(2); } } while (0)

static std::vector<char> read_file(const std::string & path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) { std::fprintf(stderr, "cannot open %s\n", path.c_str()); std::exit(2); }
    return std::vector<char>((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
}

struct Args {
    std::string spv;
    uint32_t block = 32, groups = 4096, inner = 128, reps = 5;
    double macs_per_iter = 1.0;  // 4 for a vec4 pattern, 1 for a scalar pattern
};

static Args parse(int argc, char ** argv) {
    Args args;
    for (int i = 1; i < argc; ++i) {
        const std::string key = argv[i];
        const char * value = (i + 1 < argc) ? argv[++i] : nullptr;
        if (!value) { std::fprintf(stderr, "missing value for %s\n", key.c_str()); std::exit(2); }
        if (key == "--spv") args.spv = value;
        else if (key == "--block") args.block = (uint32_t) std::strtoul(value, nullptr, 10);
        else if (key == "--groups") args.groups = (uint32_t) std::strtoul(value, nullptr, 10);
        else if (key == "--inner") args.inner = (uint32_t) std::strtoul(value, nullptr, 10);
        else if (key == "--reps") args.reps = (uint32_t) std::strtoul(value, nullptr, 10);
        else if (key == "--macs") args.macs_per_iter = std::strtod(value, nullptr);
        else { std::fprintf(stderr, "unknown argument %s\n", key.c_str()); std::exit(2); }
    }
    if (args.spv.empty()) { std::fprintf(stderr, "--spv is required\n"); std::exit(2); }
    if (args.block == 0 || args.groups == 0 || args.inner == 0 || args.reps == 0) {
        std::fprintf(stderr, "block, groups, inner and reps must be non-zero\n");
        std::exit(2);
    }
    return args;
}

int main(int argc, char ** argv) {
    const Args args = parse(argc, argv);

    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.apiVersion = VK_API_VERSION_1_1;
    VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ici.pApplicationInfo = &app;
    VkInstance instance = VK_NULL_HANDLE;
    VKC(vkCreateInstance(&ici, nullptr, &instance));

    uint32_t count = 0;
    VKC(vkEnumeratePhysicalDevices(instance, &count, nullptr));
    if (count == 0) { std::fprintf(stderr, "no Vulkan device\n"); return 2; }
    std::vector<VkPhysicalDevice> devices(count);
    VKC(vkEnumeratePhysicalDevices(instance, &count, devices.data()));
    VkPhysicalDevice physical = devices[0];
    VkPhysicalDeviceProperties props{};
    vkGetPhysicalDeviceProperties(physical, &props);

    uint32_t family_count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &family_count, nullptr);
    std::vector<VkQueueFamilyProperties> families(family_count);
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &family_count, families.data());
    uint32_t family = UINT32_MAX;
    for (uint32_t i = 0; i < family_count; ++i) {
        if (families[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { family = i; break; }
    }
    if (family == UINT32_MAX) { std::fprintf(stderr, "no compute queue\n"); return 2; }

    const float priority = 1.0f;
    VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    VkDevice device = VK_NULL_HANDLE;
    VKC(vkCreateDevice(physical, &dci, nullptr, &device));
    VkQueue queue = VK_NULL_HANDLE;
    vkGetDeviceQueue(device, family, 0, &queue);

    auto make_buffer = [&](VkDeviceSize bytes, VkBuffer & buffer, VkDeviceMemory & memory) {
        VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
        bci.size = bytes;
        bci.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
        bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        VKC(vkCreateBuffer(device, &bci, nullptr, &buffer));
        VkMemoryRequirements req{};
        vkGetBufferMemoryRequirements(device, buffer, &req);
        VkPhysicalDeviceMemoryProperties memory_props{};
        vkGetPhysicalDeviceMemoryProperties(physical, &memory_props);
        uint32_t type = UINT32_MAX;
        for (uint32_t i = 0; i < memory_props.memoryTypeCount; ++i) {
            const bool host_visible = memory_props.memoryTypes[i].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT;
            if ((req.memoryTypeBits & (1u << i)) && host_visible) { type = i; break; }
        }
        if (type == UINT32_MAX) { std::fprintf(stderr, "no host visible memory\n"); std::exit(2); }
        VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        mai.allocationSize = req.size;
        mai.memoryTypeIndex = type;
        VKC(vkAllocateMemory(device, &mai, nullptr, &memory));
        VKC(vkBindBufferMemory(device, buffer, memory, 0));
    };

    const uint32_t vec4_count = 1u << 16;  // 64K vec4 for A, same for B
    VkBuffer buffer_a = VK_NULL_HANDLE, buffer_b = VK_NULL_HANDLE, buffer_o = VK_NULL_HANDLE;
    VkDeviceMemory mem_a = VK_NULL_HANDLE, mem_b = VK_NULL_HANDLE, mem_o = VK_NULL_HANDLE;
    make_buffer(VkDeviceSize(vec4_count) * 16, buffer_a, mem_a);
    make_buffer(VkDeviceSize(vec4_count) * 16, buffer_b, mem_b);
    make_buffer(VkDeviceSize(args.groups) * VkDeviceSize(args.block) * 4, buffer_o, mem_o);

    float * mapped = nullptr;
    VKC(vkMapMemory(device, mem_a, 0, VK_WHOLE_SIZE, 0, reinterpret_cast<void **>(&mapped)));
    for (uint32_t i = 0; i < vec4_count * 4; ++i) mapped[i] = 0.5f;
    vkUnmapMemory(device, mem_a);
    VKC(vkMapMemory(device, mem_b, 0, VK_WHOLE_SIZE, 0, reinterpret_cast<void **>(&mapped)));
    for (uint32_t i = 0; i < vec4_count * 4; ++i) mapped[i] = 0.25f;
    vkUnmapMemory(device, mem_b);

    VkDescriptorSetLayoutBinding bindings[3]{};
    for (uint32_t i = 0; i < 3; ++i) {
        bindings[i].binding = i;
        bindings[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        bindings[i].descriptorCount = 1;
        bindings[i].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    }
    VkDescriptorSetLayoutCreateInfo dslci{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};
    dslci.bindingCount = 3;
    dslci.pBindings = bindings;
    VkDescriptorSetLayout set_layout = VK_NULL_HANDLE;
    VKC(vkCreateDescriptorSetLayout(device, &dslci, nullptr, &set_layout));

    VkPushConstantRange range{};
    range.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
    range.offset = 0;
    range.size = sizeof(uint32_t);
    VkPipelineLayoutCreateInfo plci{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    plci.setLayoutCount = 1;
    plci.pSetLayouts = &set_layout;
    plci.pushConstantRangeCount = 1;
    plci.pPushConstantRanges = &range;
    VkPipelineLayout pipeline_layout = VK_NULL_HANDLE;
    VKC(vkCreatePipelineLayout(device, &plci, nullptr, &pipeline_layout));

    const std::vector<char> spv = read_file(args.spv);
    VkShaderModuleCreateInfo smci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    smci.codeSize = spv.size();
    smci.pCode = reinterpret_cast<const uint32_t *>(spv.data());
    VkShaderModule module = VK_NULL_HANDLE;
    VKC(vkCreateShaderModule(device, &smci, nullptr, &module));

    VkSpecializationMapEntry entry{};
    entry.constantID = 0;
    entry.offset = 0;
    entry.size = sizeof(uint32_t);
    VkSpecializationInfo spec{};
    spec.mapEntryCount = 1;
    spec.pMapEntries = &entry;
    spec.dataSize = sizeof(uint32_t);
    spec.pData = &args.block;

    VkComputePipelineCreateInfo cpci{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    cpci.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    cpci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    cpci.stage.module = module;
    cpci.stage.pName = "main";
    cpci.stage.pSpecializationInfo = &spec;
    cpci.layout = pipeline_layout;
    VkPipeline pipeline = VK_NULL_HANDLE;
    VKC(vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &cpci, nullptr, &pipeline));

    VkDescriptorPoolSize pool_size{};
    pool_size.type = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
    pool_size.descriptorCount = 3;
    VkDescriptorPoolCreateInfo dpci{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};
    dpci.maxSets = 1;
    dpci.poolSizeCount = 1;
    dpci.pPoolSizes = &pool_size;
    VkDescriptorPool pool = VK_NULL_HANDLE;
    VKC(vkCreateDescriptorPool(device, &dpci, nullptr, &pool));
    VkDescriptorSetAllocateInfo dsai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};
    dsai.descriptorPool = pool;
    dsai.descriptorSetCount = 1;
    dsai.pSetLayouts = &set_layout;
    VkDescriptorSet set = VK_NULL_HANDLE;
    VKC(vkAllocateDescriptorSets(device, &dsai, &set));

    VkDescriptorBufferInfo infos[3] = {
        {buffer_a, 0, VK_WHOLE_SIZE}, {buffer_b, 0, VK_WHOLE_SIZE}, {buffer_o, 0, VK_WHOLE_SIZE}};
    VkWriteDescriptorSet writes[3]{};
    for (uint32_t i = 0; i < 3; ++i) {
        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = set;
        writes[i].dstBinding = i;
        writes[i].descriptorCount = 1;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;
        writes[i].pBufferInfo = &infos[i];
    }
    vkUpdateDescriptorSets(device, 3, writes, 0, nullptr);

    VkCommandPoolCreateInfo cpoolci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    cpoolci.queueFamilyIndex = family;
    VkCommandPool command_pool = VK_NULL_HANDLE;
    VKC(vkCreateCommandPool(device, &cpoolci, nullptr, &command_pool));
    VkCommandBufferAllocateInfo cbai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    cbai.commandPool = command_pool;
    cbai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cbai.commandBufferCount = 1;
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    VKC(vkAllocateCommandBuffers(device, &cbai, &cmd));

    VkCommandBufferBeginInfo cbbi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VKC(vkBeginCommandBuffer(cmd, &cbbi));
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline_layout, 0, 1, &set, 0, nullptr);
    vkCmdPushConstants(cmd, pipeline_layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(uint32_t), &args.inner);
    vkCmdDispatch(cmd, args.groups, 1, 1);
    VKC(vkEndCommandBuffer(cmd));

    VkFenceCreateInfo fci{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence = VK_NULL_HANDLE;
    VKC(vkCreateFence(device, &fci, nullptr, &fence));

    auto submit_once = [&]() {
        VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};
        si.commandBufferCount = 1;
        si.pCommandBuffers = &cmd;
        VKC(vkQueueSubmit(queue, 1, &si, fence));
        VKC(vkWaitForFences(device, 1, &fence, VK_TRUE, UINT64_MAX));
        VKC(vkResetFences(device, 1, &fence));
    };

    submit_once();  // warm up: shader JIT, first-touch of the buffers
    const auto start_time = std::chrono::steady_clock::now();
    for (uint32_t r = 0; r < args.reps; ++r) submit_once();
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time).count();

    const double invocations = double(args.groups) * args.block;
    const double macs = invocations * double(args.inner) * args.macs_per_iter;
    std::printf("device=%s driver_version=%u block=%u groups=%u inner=%u macs_per_iter=%.1f reps=%u "
                "ms=%.3f gmacs_per_s=%.3f gpairs_per_s=%.3f\n",
                props.deviceName, props.driverVersion, args.block, args.groups, args.inner,
                args.macs_per_iter, args.reps, seconds * 1000.0 / args.reps,
                macs / seconds / 1e9, invocations * args.inner / seconds / 1e9);

    vkDestroyFence(device, fence, nullptr);
    vkDestroyCommandPool(device, command_pool, nullptr);
    vkDestroyDescriptorPool(device, pool, nullptr);
    vkDestroyPipeline(device, pipeline, nullptr);
    vkDestroyShaderModule(device, module, nullptr);
    vkDestroyPipelineLayout(device, pipeline_layout, nullptr);
    vkDestroyDescriptorSetLayout(device, set_layout, nullptr);
    vkDestroyBuffer(device, buffer_a, nullptr);
    vkDestroyBuffer(device, buffer_b, nullptr);
    vkDestroyBuffer(device, buffer_o, nullptr);
    vkFreeMemory(device, mem_a, nullptr);
    vkFreeMemory(device, mem_b, nullptr);
    vkFreeMemory(device, mem_o, nullptr);
    vkDestroyDevice(device, nullptr);
    vkDestroyInstance(instance, nullptr);
    return 0;
}

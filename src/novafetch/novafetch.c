#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/utsname.h>
#include <unistd.h>

static unsigned long mem_kb(const char *key)
{
	char line[128];
	FILE *f = fopen("/proc/meminfo", "r");
	if (!f) return 0;
	while (fgets(line, sizeof(line), f)) {
		if (!strncmp(line, key, strlen(key))) {
			fclose(f);
			return strtoul(line + strlen(key), NULL, 10);
		}
	}
	fclose(f);
	return 0;
}

int main(void)
{
	struct utsname u;
	unsigned long tot = mem_kb("MemTotal:"), avail = mem_kb("MemAvailable:");
	uname(&u);
	printf("\n");
	printf("        ☆  nova@%s\n", u.nodename);
	printf("       ☆☆  ---------------\n");
	printf("      ☆  ☆ OS:      NovaLinux 1.0\n");
	printf("     ☆    ☆ Host:    novastation\n");
	printf("    ☆  ✦  ☆ Kernel:  %s\n", u.release);
	printf("     ☆    ☆ CPU:     Intel Pentium N5030 (Goldmont Plus)\n");
	printf("      ☆  ☆ Arch:    %s\n", u.machine);
	printf("       ☆☆  Init:    OpenRC\n");
	printf("        ☆  DE:      NovaUI\n");
	printf("           Shell:   ash\n");
	printf("           Pkgs:    NovaPKG\n");
	if (tot)
		printf("           Memory:  %lu MiB / %lu MiB\n", (tot - avail) / 1024, tot / 1024);
	printf("\n");
	return 0;
}

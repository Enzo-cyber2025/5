/* nova-oom — earlyoom-style userspace OOM killer */
#include <dirent.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned long mem(const char *k)
{
	char l[128];
	FILE *f = fopen("/proc/meminfo", "r");
	if (!f) return 0;
	while (fgets(l, sizeof(l), f))
		if (!strncmp(l, k, strlen(k))) {
			fclose(f);
			return strtoul(l + strlen(k), NULL, 10);
		}
	fclose(f);
	return 0;
}

static int victim(void)
{
	DIR *d = opendir("/proc");
	struct dirent *e;
	int best = 1, bestoom = -1000;
	if (!d) return 1;
	while ((e = readdir(d))) {
		char p[64], buf[64];
		FILE *f;
		int oom = 0, pid;
		if (e->d_name[0] < '1' || e->d_name[0] > '9') continue;
		pid = atoi(e->d_name);
		if (pid <= 1) continue;
		snprintf(p, sizeof(p), "/proc/%d/oom_score", pid);
		f = fopen(p, "r");
		if (!f) continue;
		if (fgets(buf, sizeof(buf), f)) oom = atoi(buf);
		fclose(f);
		if (oom > bestoom) { bestoom = oom; best = pid; }
	}
	closedir(d);
	return best;
}

int main(void)
{
	for (;;) {
		unsigned long tot = mem("MemTotal:"), avail = mem("MemAvailable:");
		if (tot && avail * 100 / tot < 4) {
			int p = victim();
			if (p > 1) {
				fprintf(stderr, "nova-oom: sending SIGTERM to %d (mem %lu/%lu kB)\n",
					p, avail, tot);
				kill(p, SIGTERM);
				sleep(2);
				kill(p, SIGKILL);
			}
		}
		sleep(1);
	}
}

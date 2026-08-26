/* nova-preload — readahead common binaries after boot */
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

static const char *list[] = {
	"/usr/bin/novashell",
	"/usr/bin/novapkg",
	"/usr/bin/novafetch",
	"/bin/busybox",
	"/bin/sh",
	"/etc/novaui",
	NULL
};

int main(void)
{
	int i;
	sleep(2);
	for (i = 0; list[i]; i++) {
		int fd = open(list[i], O_RDONLY);
		if (fd >= 0) {
			char buf[4096];
			while (read(fd, buf, sizeof(buf)) > 0) {}
			close(fd);
		}
	}
	return 0;
}

/* Autologin as nova (uid 1000) and start NovaUI. */
#include <fcntl.h>
#include <grp.h>
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(void)
{
	struct passwd *pw = getpwnam("nova");
	uid_t uid = pw ? pw->pw_uid : 1000;
	gid_t gid = pw ? pw->pw_gid : 1000;
	const char *home = pw && pw->pw_dir ? pw->pw_dir : "/home/nova";
	const char *shell = "/usr/bin/novashell";

	setenv("HOME", home, 1);
	setenv("USER", "nova", 1);
	setenv("LOGNAME", "nova", 1);
	setenv("PATH", "/usr/local/bin:/usr/bin:/bin:/sbin:/usr/sbin", 1);
	setenv("LANG", "en_US.UTF-8", 1);
	setenv("LC_ALL", "en_US.UTF-8", 1);
	setenv("TERM", "linux", 1);
	setenv("HOSTNAME", "novastation", 1);
	initgroups("nova", gid);
	setgid(gid);
	setuid(uid);
	chdir(home);
	{
		int fd = open("/dev/tty1", O_WRONLY);
		if (fd < 0) fd = open("/dev/console", O_WRONLY);
		if (fd >= 0) {
			const char *m =
				"\n\n  NovaLinux 1.0\n"
				"  starting NovaUI...\n\n";
			if (write(fd, m, strlen(m)) < 0) {}
			close(fd);
		}
	}
	execl(shell, "novashell", "session", (char *)NULL);
	execl("/bin/sh", "-sh", "-l", (char *)NULL);
	perror("exec");
	return 1;
}

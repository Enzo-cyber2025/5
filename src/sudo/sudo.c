/* Passwordless sudo for user nova (uid 1000). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv)
{
	uid_t u = getuid();
	if (u != 0 && u != 1000) {
		fprintf(stderr, "sudo: only nova may use sudo\n");
		return 1;
	}
	if (argc < 2) {
		fprintf(stderr, "usage: sudo <command> [args]\n");
		return 1;
	}
	if (setuid(0) < 0 || setgid(0) < 0) {
		perror("sudo: setuid");
		return 1;
	}
	setenv("SUDO_USER", "nova", 1);
	execvp(argv[1], argv + 1);
	perror(argv[1]);
	return 127;
}

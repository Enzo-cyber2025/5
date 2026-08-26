/* NovaPKG — native package manager. Packages are .nvpkg (tar.xz + metadata.json). */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#define DB_DIR   "/var/lib/novapkg"
#define DB_FILE  "/var/lib/novapkg/db"
#define REPO_DIR "/var/lib/novapkg/repo"
#define CACHE    "/var/cache/novapkg"

typedef struct {
	char name[64];
	char version[32];
	char arch[16];
	char description[256];
	char depends[256];
	char files[32][256];
	int nfiles;
} Pkg;

static void die(const char *m)
{
	fprintf(stderr, "novapkg: %s\n", m);
	exit(1);
}

static int run(const char *cmd)
{
	int st = system(cmd);
	return WIFEXITED(st) ? WEXITSTATUS(st) : 1;
}

static void ensure_dirs(void)
{
	mkdir("/var", 0755);
	mkdir("/var/lib", 0755);
	mkdir(DB_DIR, 0755);
	mkdir(REPO_DIR, 0755);
	mkdir("/var/cache", 0755);
	mkdir(CACHE, 0755);
}

static int json_get(const char *js, const char *key, char *out, size_t n)
{
	char pat[80];
	const char *p, *q;
	snprintf(pat, sizeof(pat), "\"%s\"", key);
	p = strstr(js, pat);
	if (!p) return 0;
	p = strchr(p + strlen(pat), ':');
	if (!p) return 0;
	p++;
	while (*p == ' ' || *p == '\t') p++;
	if (*p == '"') {
		p++;
		q = strchr(p, '"');
		if (!q) return 0;
		if ((size_t)(q - p) >= n) return 0;
		memcpy(out, p, (size_t)(q - p));
		out[q - p] = 0;
		return 1;
	}
	q = p;
	while (*q && *q != ',' && *q != '}' && *q != '\n') q++;
	while (q > p && (q[-1] == ' ' || q[-1] == '\t')) q--;
	if ((size_t)(q - p) >= n) return 0;
	memcpy(out, p, (size_t)(q - p));
	out[q - p] = 0;
	return 1;
}

static int load_meta(const char *path, Pkg *pkg)
{
	char buf[8192];
	FILE *f = fopen(path, "r");
	size_t n;
	memset(pkg, 0, sizeof(*pkg));
	if (!f) return -1;
	n = fread(buf, 1, sizeof(buf) - 1, f);
	buf[n] = 0;
	fclose(f);
	json_get(buf, "name", pkg->name, sizeof(pkg->name));
	json_get(buf, "version", pkg->version, sizeof(pkg->version));
	json_get(buf, "arch", pkg->arch, sizeof(pkg->arch));
	json_get(buf, "description", pkg->description, sizeof(pkg->description));
	json_get(buf, "depends", pkg->depends, sizeof(pkg->depends));
	{
		const char *p = strstr(buf, "\"files\"");
		if (p) {
			p = strchr(p, '[');
			if (p) {
				p++;
				while (*p && *p != ']' && pkg->nfiles < 32) {
					const char *q;
					while (*p && *p != '"' && *p != ']') p++;
					if (*p != '"') break;
					p++;
					q = strchr(p, '"');
					if (!q) break;
					if ((size_t)(q - p) < sizeof(pkg->files[0])) {
						memcpy(pkg->files[pkg->nfiles], p, (size_t)(q - p));
						pkg->files[pkg->nfiles][q - p] = 0;
						pkg->nfiles++;
					}
					p = q + 1;
				}
			}
		}
	}
	return pkg->name[0] ? 0 : -1;
}

static int db_has(const char *name, Pkg *out)
{
	char path[256];
	snprintf(path, sizeof(path), DB_DIR "/%s.json", name);
	if (access(path, R_OK) != 0) return 0;
	if (out) load_meta(path, out);
	return 1;
}

static void db_put(const Pkg *p, const char *srcmeta)
{
	char dest[256], cmd[512];
	snprintf(dest, sizeof(dest), DB_DIR "/%s.json", p->name);
	snprintf(cmd, sizeof(cmd), "cp '%s' '%s'", srcmeta, dest);
	run(cmd);
}

static void db_del(const char *name)
{
	char path[256];
	snprintf(path, sizeof(path), DB_DIR "/%s.json", name);
	unlink(path);
}

static int extract_nvpkg(const char *file, char *workdir, size_t n)
{
	char cmd[1024];
	snprintf(workdir, n, CACHE "/work-%d", (int)getpid());
	snprintf(cmd, sizeof(cmd), "rm -rf '%s' && mkdir -p '%s' && tar -C '%s' -xJf '%s'",
		 workdir, workdir, workdir, file);
	if (run(cmd) != 0) {
		/* gzip fallback */
		snprintf(cmd, sizeof(cmd), "tar -C '%s' -xzf '%s'", workdir, file);
		if (run(cmd) != 0)
			return -1;
	}
	return 0;
}

static int cmd_install(const char *spec)
{
	char work[256], meta[300], root[300], cmd[1024];
	Pkg p;
	const char *file = spec;
	char found[512];
	ensure_dirs();
	if (access(spec, R_OK) != 0) {
		snprintf(found, sizeof(found), REPO_DIR "/%s.nvpkg", spec);
		if (access(found, R_OK) != 0)
			die("package file not found (offline repo only)");
		file = found;
	}
	if (extract_nvpkg(file, work, sizeof(work)) < 0)
		die("failed to unpack .nvpkg");
	snprintf(meta, sizeof(meta), "%s/metadata.json", work);
	if (load_meta(meta, &p) < 0)
		die("metadata.json missing or invalid");
	if (db_has(p.name, NULL)) {
		fprintf(stderr, "novapkg: %s already installed, replacing\n", p.name);
	}
	snprintf(root, sizeof(root), "%s/root", work);
	if (access(root, R_OK) == 0)
		snprintf(cmd, sizeof(cmd), "cp -a '%s/.' /", root);
	else
		snprintf(cmd, sizeof(cmd), "tar -C / -xf '%s/files.tar' 2>/dev/null || true", work);
	if (run(cmd) != 0)
		fprintf(stderr, "novapkg: warning: some files failed to install\n");
	{
		char post[320];
		snprintf(post, sizeof(post), "%s/scripts/postinst", work);
		if (access(post, X_OK) == 0) {
			snprintf(cmd, sizeof(cmd), "'%s'", post);
			run(cmd);
		}
	}
	db_put(&p, meta);
	printf("installed %s %s (%s)\n", p.name, p.version, p.arch);
	snprintf(cmd, sizeof(cmd), "rm -rf '%s'", work);
	run(cmd);
	return 0;
}

static int cmd_remove(const char *name)
{
	Pkg p;
	int i;
	char cmd[600];
	ensure_dirs();
	if (!db_has(name, &p))
		die("package not installed");
	for (i = 0; i < p.nfiles; i++) {
		if (p.files[i][0] == 0) continue;
		if (p.files[i][0] == '/')
			unlink(p.files[i]);
		else {
			char path[300];
			snprintf(path, sizeof(path), "/%s", p.files[i]);
			unlink(path);
		}
	}
	snprintf(cmd, sizeof(cmd), "rm -f " DB_DIR "/%s.files", name);
	run(cmd);
	db_del(name);
	printf("removed %s\n", name);
	return 0;
}

static int cmd_update(void)
{
	DIR *d;
	struct dirent *de;
	int n = 0;
	ensure_dirs();
	printf("NovaPKG update (offline repository %s)\n", REPO_DIR);
	d = opendir(REPO_DIR);
	if (!d) {
		printf("no repository packages.\n");
		return 0;
	}
	while ((de = readdir(d))) {
		char path[400];
		if (!strstr(de->d_name, ".nvpkg")) continue;
		snprintf(path, sizeof(path), "%s/%s", REPO_DIR, de->d_name);
		printf("  repo: %s\n", de->d_name);
		n++;
	}
	closedir(d);
	printf("%d package(s) available offline.\n", n);
	return 0;
}

static int cmd_search(const char *q)
{
	DIR *d;
	struct dirent *de;
	ensure_dirs();
	d = opendir(REPO_DIR);
	if (!d) d = opendir(DB_DIR);
	if (!d) { printf("nothing to search.\n"); return 0; }
	while ((de = readdir(d))) {
		Pkg p;
		char path[400], meta[400], work[256];
		if (strstr(de->d_name, ".nvpkg")) {
			snprintf(path, sizeof(path), "%s/%s", REPO_DIR, de->d_name);
			if (extract_nvpkg(path, work, sizeof(work)) == 0) {
				snprintf(meta, sizeof(meta), "%s/metadata.json", work);
				if (load_meta(meta, &p) == 0) {
					if (!q || strcasestr(p.name, q) || strcasestr(p.description, q))
						printf("%-16s %-10s %s\n", p.name, p.version, p.description);
				}
				snprintf(path, sizeof(path), "rm -rf '%s'", work);
				run(path);
			}
		} else if (strstr(de->d_name, ".json")) {
			snprintf(path, sizeof(path), "%s/%s", DB_DIR, de->d_name);
			if (load_meta(path, &p) == 0) {
				if (!q || strcasestr(p.name, q) || strcasestr(p.description, q))
					printf("%-16s %-10s %s  [installed]\n", p.name, p.version, p.description);
			}
		}
	}
	closedir(d);
	return 0;
}

static int cmd_info(const char *name)
{
	Pkg p;
	char path[256];
	int i;
	ensure_dirs();
	snprintf(path, sizeof(path), DB_DIR "/%s.json", name);
	if (load_meta(path, &p) != 0) {
		char nv[300];
		snprintf(nv, sizeof(nv), REPO_DIR "/%s.nvpkg", name);
		if (access(nv, R_OK) == 0) {
			char work[256], meta[320];
			if (extract_nvpkg(nv, work, sizeof(work)) == 0) {
				snprintf(meta, sizeof(meta), "%s/metadata.json", work);
				load_meta(meta, &p);
				snprintf(path, sizeof(path), "rm -rf '%s'", work);
				run(path);
			}
		}
	}
	if (!p.name[0])
		die("package not found");
	printf("Name:        %s\n", p.name);
	printf("Version:     %s\n", p.version);
	printf("Architecture:%s\n", p.arch[0] ? p.arch : "x86_64");
	printf("Description: %s\n", p.description);
	printf("Depends:     %s\n", p.depends[0] ? p.depends : "-");
	printf("Installed:   %s\n", db_has(p.name, NULL) ? "yes" : "no");
	if (p.nfiles) {
		printf("Files:\n");
		for (i = 0; i < p.nfiles; i++)
			printf("  %s\n", p.files[i]);
	}
	return 0;
}

static void usage(void)
{
	fprintf(stderr,
		"NovaPKG 1.0 — NovaLinux package manager\n"
		"usage: novapkg <command> [args]\n"
		"  install <file.nvpkg|name>\n"
		"  remove  <name>\n"
		"  update\n"
		"  search  [query]\n"
		"  info    <name>\n");
}

int main(int argc, char **argv)
{
	if (argc < 2) { usage(); return 1; }
	if (!strcmp(argv[1], "install") && argc >= 3) return cmd_install(argv[2]);
	if (!strcmp(argv[1], "remove") && argc >= 3) return cmd_remove(argv[2]);
	if (!strcmp(argv[1], "update")) return cmd_update();
	if (!strcmp(argv[1], "search")) return cmd_search(argc >= 3 ? argv[2] : "");
	if (!strcmp(argv[1], "info") && argc >= 3) return cmd_info(argv[2]);
	usage();
	return 1;
}

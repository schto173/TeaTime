/*
 * Tea Time - Mumble plugin for the WoW Forever beta.
 *
 * What it does, all inside the player's own Mumble client:
 *   1. Finds the running WoW process and, from its location, the file
 *      <game folder>/Logs/General.log.
 *   2. Tails that file for the "TEATIME_E v2 ..." lines written by the
 *      TeaTime addon (JOIN / BEAT / LEAVE / TEST).
 *   3. While the player is sitting at a campfire it supplies positional
 *      audio (position + facing, context = map id), so voices fade with
 *      distance and pan left/right.
 *   4. Tells the server-side bot where the player is sitting (zone id and
 *      position, only while seated), using Mumble's plugin-data messages, so
 *      the bot can move the player to the channel of that campfire. The
 *      character name is never sent.
 *
 * Built against Mumble plugin API 1.0.0 so it also loads in older clients.
 *
 * Build (see build.sh): the official MumblePlugin.h header must sit next to
 * this file.
 */
#include "MumblePlugin.h"

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#	define WIN32_LEAN_AND_MEAN
#	include <share.h>
#	include <windows.h>
#else
#	include <signal.h>
#	include <time.h>
#endif

/* ---------------------------------------------------------------- settings */

#define TT_BOT_NAME "SuperUser" /* Mumble user the zone updates are sent to */
#define TT_DATA_ID "TeaTime"    /* id of the plugin-data messages (<=100 bytes) */
#define TT_YARD 0.9144f         /* WoW yards -> Mumble metres */
#define TT_POLL_SECONDS 0.1     /* how often the log file is checked */
#define TT_RESEND_SECONDS 30.0  /* heartbeat to the bot while seated */

/*
 * Axis conventions. ASSUMPTION, still to be verified in game with two players:
 * in the values the addon logs, x grows towards north and y grows towards
 * west, and facing 0 = north, growing counter-clockwise (towards west).
 * Mumble is left-handed: +x = right/east, +y = up, +z = forward/north.
 * If left and right sound swapped or turned, flip or swap these.
 */
#ifndef TT_NORTH_FROM_X
#	define TT_NORTH_FROM_X 1.0f
#endif
#ifndef TT_EAST_FROM_Y
#	define TT_EAST_FROM_Y (-1.0f)
#endif
#ifndef TT_FACING_SIGN
#	define TT_FACING_SIGN 1.0f
#endif

/* ------------------------------------------------------------------- state */

static mumble_plugin_id_t g_id;
static mumble_api_t g_api;
static bool g_apiOk = false;
static bool g_posEnabled = true;

static char g_logPath[2048];
static FILE *g_fp = NULL;
static long g_pos = 0;
static char g_buf[1 << 17];
static size_t g_len = 0;
static double g_lastPoll = 0;
static double g_timeout = 90.0;

#ifdef _WIN32
static HANDLE g_proc = NULL;
#else
static long g_pid = 0;
#endif

static bool g_seated = false;
static int g_map = -1;
static float g_x = NAN, g_y = NAN, g_facing = NAN;
static double g_lastSeen = 0;
static char g_context[64] = "idle";

static bool g_sentSeated = false;
static int g_sentMap = -1;
static float g_sentX = NAN, g_sentY = NAN;
static double g_sentAt = -1e9;
static double g_lastTry = -1e9;
static bool g_forceSend = false;

/* --------------------------------------------------------------- utilities */

static double now_s(void) {
#ifdef _WIN32
	return (double) GetTickCount64() / 1000.0;
#else
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (double) ts.tv_sec + (double) ts.tv_nsec / 1e9;
#endif
}

static void tt_log(const char *msg) {
	if (g_apiOk && g_api.log) {
		g_api.log(g_id, msg);
	}
}

static struct MumbleStringWrapper wrap(const char *s) {
	struct MumbleStringWrapper w;
	w.data = s;
	w.size = strlen(s);
	w.needsReleasing = false;
	return w;
}

static bool starts_with_nocase(const char *s, const char *prefix) {
	while (*prefix) {
		if (tolower((unsigned char) *s++) != tolower((unsigned char) *prefix++)) {
			return false;
		}
	}
	return true;
}

static float parse_num(const char *s) {
	if (!s || (s[0] == '-' && s[1] == '\0')) {
		return NAN;
	}
	return (float) atof(s);
}

static FILE *tt_fopen(const char *utf8) {
#ifdef _WIN32
	wchar_t w[2048];
	if (!MultiByteToWideChar(CP_UTF8, 0, utf8, -1, w, 2048)) {
		return NULL;
	}
	return _wfsopen(w, L"rb", _SH_DENYNO); /* the game keeps the file open */
#else
	return fopen(utf8, "rb");
#endif
}

static void tt_close(void) {
	if (g_fp) {
		fclose(g_fp);
		g_fp = NULL;
	}
#ifdef _WIN32
	if (g_proc) {
		CloseHandle(g_proc);
		g_proc = NULL;
	}
#else
	g_pid = 0;
#endif
	g_len = 0;
}

/* Works out <game folder>/Logs/General.log for the given process. */
static bool tt_locate_log(uint64_t pid) {
	const char *override = getenv("TEATIME_LOG");
	if (override && *override) {
		snprintf(g_logPath, sizeof g_logPath, "%s", override);
		return true;
	}
#ifdef _WIN32
	HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, FALSE, (DWORD) pid);
	if (!h) {
		return false;
	}
	wchar_t exe[2048];
	DWORD size = 2048;
	if (!QueryFullProcessImageNameW(h, 0, exe, &size)) {
		CloseHandle(h);
		return false;
	}
	wchar_t *slash = wcsrchr(exe, L'\\');
	if (!slash) {
		CloseHandle(h);
		return false;
	}
	*slash = 0;
	wchar_t full[2048];
	_snwprintf(full, 2048, L"%ls\\Logs\\General.log", exe);
	if (!WideCharToMultiByte(CP_UTF8, 0, full, -1, g_logPath, (int) sizeof g_logPath, NULL, NULL)) {
		CloseHandle(h);
		return false;
	}
	g_proc = h; /* kept to notice when the game exits */
	return true;
#else
	(void) pid;
	return false; /* on non-Windows the path must come from TEATIME_LOG */
#endif
}

static bool tt_process_alive(void) {
#ifdef _WIN32
	return g_proc && WaitForSingleObject(g_proc, 0) == WAIT_TIMEOUT;
#else
	return g_pid > 0 && kill((pid_t) g_pid, 0) == 0;
#endif
}

/* ----------------------------------------------------------- log handling */

/* One line after the "TEATIME_E v2 " marker:
 *   <KIND> <map> <instance> <x> <y> <facing> <character name>
 * The character name is deliberately ignored. */
static void tt_handle(const char *s) {
	char kind[16], map[32], inst[32], xs[32], ys[32], fs[32];
	if (sscanf(s, "%15s %31s %31s %31s %31s %31s", kind, map, inst, xs, ys, fs) < 6) {
		return;
	}
	double t = now_s();

	if (strcmp(kind, "LEAVE") == 0) {
		g_seated = false;
		return;
	}
	if (strcmp(kind, "JOIN") != 0 && strcmp(kind, "BEAT") != 0 && strcmp(kind, "TEST") != 0) {
		return;
	}
	g_seated = true;
	g_map = (map[0] == '-') ? -1 : atoi(map);
	g_x = parse_num(xs);
	g_y = parse_num(ys);
	g_facing = parse_num(fs);
	g_lastSeen = t;
	snprintf(g_context, sizeof g_context, "map%d", g_map);
}

static void tt_process_buffer(void) {
	char *start = g_buf;
	char *end;
	g_buf[g_len] = '\0';
	while ((end = memchr(start, '\n', g_len - (size_t) (start - g_buf))) != NULL) {
		*end = '\0';
		if (end > start && end[-1] == '\r') {
			end[-1] = '\0';
		}
		const char *m = strstr(start, "TEATIME_E v2 ");
		if (m) {
			tt_handle(m + 13);
		}
		start = end + 1;
	}
	size_t rest = g_len - (size_t) (start - g_buf);
	/* Only a complete line is ever processed: the game flushes its buffer in
	 * ~50 KB steps that can cut a line in half. Keep the partial tail. */
	if (rest >= sizeof g_buf - 1) {
		rest = 0; /* an endless line without newline: drop it */
	}
	memmove(g_buf, start, rest);
	g_len = rest;
}

static void tt_poll(void) {
	double t = now_s();
	if (t - g_lastPoll < TT_POLL_SECONDS || !g_fp) {
		return;
	}
	g_lastPoll = t;

	fseek(g_fp, 0, SEEK_END);
	long size = ftell(g_fp);
	if (size < g_pos) { /* file was truncated or replaced */
		g_pos = 0;
		g_len = 0;
	}
	if (size == g_pos) {
		return;
	}
	fseek(g_fp, g_pos, SEEK_SET);
	size_t room = sizeof g_buf - g_len - 1;
	size_t n = fread(g_buf + g_len, 1, room, g_fp);
	g_pos += (long) n;
	g_len += n;
	tt_process_buffer();
}

/* ------------------------------------------------ telling the server bot */

static bool tt_have_pos(void) {
	return isfinite(g_x) && isfinite(g_y);
}

/* true if the player sits more than 2 yards from where we last reported */
static bool tt_moved_since_sent(void) {
	if (!tt_have_pos()) {
		return false;
	}
	if (!isfinite(g_sentX) || !isfinite(g_sentY)) {
		return true;
	}
	float dx = g_x - g_sentX, dy = g_y - g_sentY;
	return dx * dx + dy * dy > 4.0f;
}

static void tt_send_status(void) {
	double t = now_s();
	bool changed = (g_seated != g_sentSeated) || (g_seated && g_map != g_sentMap) || (g_seated && tt_moved_since_sent());
	bool beat = g_seated && (t - g_sentAt) >= TT_RESEND_SECONDS;
	if (!g_forceSend && !changed && !beat) {
		return;
	}
	if (t - g_lastTry < 2.0) { /* don't hammer the API while the bot is absent */
		return;
	}
	if (t - g_sentAt < 1.0) { /* the server rate-limits plugin data: keep ~1 s apart */
		return;
	}
	if (!g_apiOk || !g_api.getActiveServerConnection || !g_api.findUserByName || !g_api.sendData) {
		return;
	}
	mumble_connection_t conn;
	mumble_userid_t bot;
	if (g_api.getActiveServerConnection(g_id, &conn) != MUMBLE_STATUS_OK
		|| g_api.findUserByName(g_id, conn, TT_BOT_NAME, &bot) != MUMBLE_STATUS_OK) {
		g_lastTry = t; /* no server or no bot right now: try again in a couple of seconds */
		return;
	}
	char msg[96];
	int n;
	if (g_seated && tt_have_pos()) {
		n = snprintf(msg, sizeof msg, "TT1 seated=1 map=%d x=%.1f y=%.1f", g_map, (double) g_x, (double) g_y);
	} else {
		n = snprintf(msg, sizeof msg, "TT1 seated=%d map=%d", g_seated ? 1 : 0, g_seated ? g_map : -1);
	}
	if (g_api.sendData(g_id, conn, &bot, 1, (const uint8_t *) msg, (size_t) n, TT_DATA_ID) == MUMBLE_STATUS_OK) {
		g_sentSeated = g_seated;
		g_sentMap = g_map;
		g_sentX = g_x;
		g_sentY = g_y;
		g_sentAt = t;
		g_forceSend = false;
	} else {
		g_lastTry = t;
	}
}

/* ------------------------------------------------- mandatory / plugin API */

MUMBLE_PLUGIN_EXPORT mumble_error_t MUMBLE_PLUGIN_CALLING_CONVENTION mumble_init(mumble_plugin_id_t id) {
	g_id = id;
	const char *to = getenv("TEATIME_TIMEOUT"); /* for testing */
	if (to && atof(to) > 0) {
		g_timeout = atof(to);
	}
	return MUMBLE_STATUS_OK;
}

MUMBLE_PLUGIN_EXPORT void MUMBLE_PLUGIN_CALLING_CONVENTION mumble_shutdown() {
	tt_close();
}

MUMBLE_PLUGIN_EXPORT struct MumbleStringWrapper MUMBLE_PLUGIN_CALLING_CONVENTION mumble_getName() {
	return wrap("TeaTime");
}

MUMBLE_PLUGIN_EXPORT mumble_version_t MUMBLE_PLUGIN_CALLING_CONVENTION mumble_getAPIVersion() {
	mumble_version_t v = { MUMBLE_PLUGIN_API_MAJOR_MACRO, MUMBLE_PLUGIN_API_MINOR_MACRO,
						   MUMBLE_PLUGIN_API_PATCH_MACRO };
	return v;
}

MUMBLE_PLUGIN_EXPORT void MUMBLE_PLUGIN_CALLING_CONVENTION mumble_registerAPIFunctions(void *apiStruct) {
	g_api = *((mumble_api_t *) apiStruct); /* must be copied, the pointer becomes invalid */
	g_apiOk = true;
}

MUMBLE_PLUGIN_EXPORT void MUMBLE_PLUGIN_CALLING_CONVENTION mumble_releaseResource(const void *pointer) {
	(void) pointer; /* every string we return is static */
}

/* ---------------------------------------------------- general information */

MUMBLE_PLUGIN_EXPORT mumble_version_t MUMBLE_PLUGIN_CALLING_CONVENTION mumble_getVersion() {
	mumble_version_t v = { 0, 2, 0 };
	return v;
}

MUMBLE_PLUGIN_EXPORT struct MumbleStringWrapper MUMBLE_PLUGIN_CALLING_CONVENTION mumble_getAuthor() {
	return wrap("Tea Time");
}

MUMBLE_PLUGIN_EXPORT struct MumbleStringWrapper MUMBLE_PLUGIN_CALLING_CONVENTION mumble_getDescription() {
	return wrap("Proximity voice for people sitting at a WoW campfire (needs the TeaTime addon).");
}

MUMBLE_PLUGIN_EXPORT uint32_t MUMBLE_PLUGIN_CALLING_CONVENTION mumble_getFeatures() {
	return MUMBLE_FEATURE_POSITIONAL;
}

MUMBLE_PLUGIN_EXPORT uint32_t MUMBLE_PLUGIN_CALLING_CONVENTION mumble_deactivateFeatures(uint32_t features) {
	if (features & MUMBLE_FEATURE_POSITIONAL) {
		g_posEnabled = false;
	}
	return MUMBLE_FEATURE_NONE; /* everything we were asked to switch off, we did */
}

/* ------------------------------------------------------- positional data */

MUMBLE_PLUGIN_EXPORT uint8_t MUMBLE_PLUGIN_CALLING_CONVENTION mumble_initPositionalData(
	const char *const *programNames, const uint64_t *programPIDs, size_t programCount) {
	if (!g_posEnabled) {
		return MUMBLE_PDEC_ERROR_TEMP;
	}
	/* Any program called Wow*.exe: Wow.exe, WowClassic.exe, WowClassicB.exe, ... */
	int found = -1;
	for (size_t i = 0; i < programCount; i++) {
		if (starts_with_nocase(programNames[i], "wow")) {
			found = (int) i;
			break;
		}
	}
	if (found < 0) {
		return MUMBLE_PDEC_ERROR_TEMP;
	}
	if (!tt_locate_log(programPIDs[found])) {
		tt_close();
		return MUMBLE_PDEC_ERROR_TEMP;
	}
#ifndef _WIN32
	g_pid = (long) programPIDs[found];
#endif
	g_fp = tt_fopen(g_logPath);
	if (!g_fp) {
		tt_close();
		return MUMBLE_PDEC_ERROR_TEMP; /* Logs/General.log does not exist (yet) */
	}
	fseek(g_fp, 0, SEEK_END); /* only events from now on, never replay old ones */
	g_pos = ftell(g_fp);
	g_len = 0;
	g_seated = false;
	g_sentSeated = false;
	g_forceSend = false;
	tt_log("TeaTime: watching the game log");
	return MUMBLE_PDEC_OK;
}

MUMBLE_PLUGIN_EXPORT bool MUMBLE_PLUGIN_CALLING_CONVENTION mumble_fetchPositionalData(
	float *avatarPos, float *avatarDir, float *avatarAxis, float *cameraPos, float *cameraDir, float *cameraAxis,
	const char **context, const char **identity) {
	for (int i = 0; i < 3; i++) {
		avatarPos[i] = avatarDir[i] = avatarAxis[i] = 0.0f;
		cameraPos[i] = cameraDir[i] = cameraAxis[i] = 0.0f;
	}
	if (!g_posEnabled || !tt_process_alive()) {
		return false; /* the game closed: Mumble will call shutdownPositionalData */
	}

	tt_poll();
	if (g_seated && now_s() - g_lastSeen > g_timeout) {
		g_seated = false; /* no heartbeat for too long: treat as gone */
	}
	tt_send_status();

	if (g_seated && isfinite(g_x) && isfinite(g_y) && isfinite(g_facing)) {
		avatarPos[0] = TT_EAST_FROM_Y * g_y * TT_YARD;
		avatarPos[1] = 0.0f;
		avatarPos[2] = TT_NORTH_FROM_X * g_x * TT_YARD;
		avatarDir[0] = -TT_FACING_SIGN * sinf(g_facing);
		avatarDir[1] = 0.0f;
		avatarDir[2] = cosf(g_facing);
		avatarAxis[1] = 1.0f;
		for (int i = 0; i < 3; i++) {
			cameraPos[i] = avatarPos[i];
			cameraDir[i] = avatarDir[i];
			cameraAxis[i] = avatarAxis[i];
		}
		*context = g_context;
	} else {
		/* Not sitting: everyone shares the same "idle" context at the origin. */
		avatarDir[2] = 1.0f;
		avatarAxis[1] = 1.0f;
		cameraDir[2] = 1.0f;
		cameraAxis[1] = 1.0f;
		*context = "idle";
	}
	*identity = ""; /* nothing that identifies the character leaves the PC */
	return true;
}

MUMBLE_PLUGIN_EXPORT void MUMBLE_PLUGIN_CALLING_CONVENTION mumble_shutdownPositionalData() {
	tt_close();
	g_seated = false;
}

/* --------------------------------------------------------------- callbacks */

MUMBLE_PLUGIN_EXPORT void MUMBLE_PLUGIN_CALLING_CONVENTION mumble_onServerSynchronized(mumble_connection_t connection) {
	(void) connection;
	if (g_seated) {
		g_forceSend = true; /* tell the bot again after (re)connecting while seated */
		g_lastTry = -1e9;
	}
}

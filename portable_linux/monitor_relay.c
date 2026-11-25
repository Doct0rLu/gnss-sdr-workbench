/* Forward unchanged GNSS-SDR datagrams from guest loopback to the Windows UI. */
#include <arpa/inet.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <unistd.h>

static int port(const char *text)
{
    char *end;
    long value = strtol(text, &end, 10);
    return *text && !*end && value > 0 && value <= UINT16_MAX ? (int)value : -1;
}

int main(int argc, char **argv)
{
    if (argc != 3 || port(argv[1]) < 0 || port(argv[2]) < 0) return 2;
    struct sockaddr_in local = {.sin_family = AF_INET, .sin_port = htons(port(argv[1])),
                                .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    struct sockaddr_in host = {.sin_family = AF_INET, .sin_port = htons(port(argv[2]))};
    inet_pton(AF_INET, "10.0.2.2", &host.sin_addr);
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    int output = socket(AF_INET, SOCK_DGRAM, 0);
    if (output < 0 || fd < 0 || bind(fd, (struct sockaddr *)&local, sizeof(local)) < 0) {
        perror("monitor relay bind");
        return 1;
    }
    unsigned char data[65536];
    for (;;) {
        ssize_t size = recv(fd, data, sizeof(data), 0);
        if (size < 0 && errno == EINTR) continue;
        if (size < 0 || sendto(output, data, size, 0, (struct sockaddr *)&host, sizeof(host)) < 0) {
            perror("monitor relay");
            close(fd);
            close(output);
            return 1;
        }
    }
}

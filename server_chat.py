# coding=utf-8
import socket
import select
import sys
import signal
import json
import time
import userDB
import hashlib
from threading import *

class Server(object):
    def __init__(self):
        self.port = 8008
        self.loginport = 8888
        self.default_listen_port = 8666
        self.default_send_port = 8686
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_login_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_default_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_default_sent_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.host = socket.gethostname()   # 获得主机名，zyt-K52Jc
        self.BACKLOG = 10  # 最大Listen连接数
        self.RECV_BUF = 4096  # 单次发送数据量
        self.socketlist = []  # 列表，包括了监听socket和各客户端连接的socket
        self.userdict = {}  # 所有用户,key是id，value是ip和昵称
        self.onlineuserdict = {}  # 只包括连接上的id：ip
        self.tokendict = {}
        self.alluser = {}

        self.defaultlist = {}
        self.t = Thread(target=self.updateuser, args=())
        self.t.start()

        signal.signal(signal.SIGTERM, self.sig_exit)
        signal.signal(signal.SIGINT, self.sig_exit)

    def updateuser(self):
        while True:
            my_info_db = userDB.UserInfoDB()
            self.alluser = my_info_db.searchAll()
            time.sleep(5)

    def start(self):
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # 重用端口，不会出现Address used
        self.server_socket.bind((self.host, self.port))  # 绑定到指定端口

        self.server_login_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_login_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.server_login_socket.bind(("127.0.0.2", self.loginport))

        self.server_default_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_default_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.server_default_socket.bind(("127.0.0.2", self.default_listen_port))

        self.server_default_sent_socket.bind(("127.0.0.2", self.default_send_port))

        self.server_socket.listen(self.BACKLOG)  # 开始监听
        self.server_login_socket.listen(self.BACKLOG)
        self.socketlist.append(self.server_socket)
        self.socketlist.append(self.server_login_socket)
        self.socketlist.append(self.server_default_socket)

        print "Server start at : " + self.host + ":" + str(self.port)

        while True:
            read_sockets, write_sockets, error_sockets = select.select(self.socketlist, [], [])  # 异步输入
            for sock in read_sockets:
                if sock == self.server_socket:
                    client_socket, client_addr = sock.accept()  # 获得请求的客户端信息

                    # 验证登录
                    login_token = client_socket.recv(self.RECV_BUF)
                    uid = login_token.split("|")[1]
                    if login_token != self.tokendict[uid]:
                        client_socket.close()
                        continue

                    # 成功则保留socket
                    self.socketlist.append(client_socket)  # 连接的客户端socket添加到列表中

                    print "Client: [%s:%s] is connected!\n" % client_addr

                    for i in self.alluser:
                        self.userdict[i[1]] = {}
                        if i[1] in self.onlineuserdict.keys():
                            self.userdict[i[1]]["ip"] = self.onlineuserdict[i[1]]
                        else:
                            self.userdict[i[1]]["ip"] = "x"
                        self.userdict[i[1]]["name"] = i[2]

                    back_info = json.dumps(self.userdict)
                    self.broadcast(sock, back_info)

                    if uid in self.defaultlist.keys():
                        for id, connent in self.defaultlist[uid].items():
                            for i in connent:
                                data = {"id": id, "msg": i}
                                data = json.dumps(data)
                                self.server_default_sent_socket.sendto(data, (client_addr[0], 2333))
                        self.defaultlist[uid] = {}
                elif sock == self.server_login_socket:
                    client_login_socket, client_login_addr = sock.accept()
                    login = client_login_socket.recv(self.RECV_BUF)
                    login = json.loads(login)
                    try:
                        user_id = login["uid"]
                        user_pwd = login["pwd"]
                    except KeyError:
                        print "login key error"
                    my_login_db = userDB.UserLoginDB()
                    res = my_login_db.search(user_id, user_pwd)
                    if res == "1":         # 0000000000000000000000
                        # 加密获得token
                        sha = hashlib.sha1()
                        sha.update(str(time.time())+ str(user_id))
                        token = sha.hexdigest() + "|" + str(user_id)
                        self.tokendict[user_id] = token

                        self.onlineuserdict[user_id] = client_login_addr[0]

                        client_login_socket.send(token)
                        client_login_socket.close()
                    else:
                        client_login_socket.send("0")
                        client_login_socket.close()
                        continue

                elif sock == self.server_default_socket:
                    data, peer_addr = sock.recvfrom(self.RECV_BUF)
                    data = json.loads(data)
                    from_id = data["id"].split("|")[0]
                    aim_id = data["id"].split("|")[1]  # 离线消息目标用户id

                    if aim_id not in self.defaultlist.keys():
                        self.defaultlist[aim_id] = {}
                    if len(self.defaultlist[aim_id]) == 0:
                        self.defaultlist[aim_id][from_id] = []
                    self.defaultlist[aim_id][from_id].append(data["msg"])  # 把消息放进该用户对应的目的ip下

    def broadcast(self, sock, msg):
        for each_sock in self.socketlist:
            if each_sock != self.server_socket and each_sock != self.server_login_socket and \
                            each_sock != self.server_default_socket and sock != each_sock:
                try:
                    each_sock.send(msg)
                except socket.error:
                    each_sock.close()
                    self.socketlist.remove(each_sock)
                    continue

    def sig_exit(self, a, b):
        for sock in self.socketlist:
            sock.close()
        print "Bye~\n"
        sys.exit(0)

if __name__ == "__main__":
    myserver = Server()
    myserver.start()

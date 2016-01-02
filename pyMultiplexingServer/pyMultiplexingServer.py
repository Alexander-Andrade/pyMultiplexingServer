import sys  #for IP and port passing
import socket
import re   #regular expressions
from FileWorker import*
from SocketWrapper import*
import time
import multiprocessing as mp
import select
from enum import Enum,unique

class QueryError(Exception):
    pass

@unique
class QueryType(Enum):
      Query = 1
      Download = 2

@unique
class QueryStatus(Enum):
      Actual = 1
      InPorgress = 2
      Complete = 3
      Error = 4

class TCPServer:

    def __init__(self, IP,port,nConnections = 1):
        self.servSock = TCP_ServSockWrapper(IP,port,nConnections) 
        self.udpServSock = UDP_ServSockWrapper(IP,port)
        self.clients = []

    def __registerNewClient(self):
        sock, addr = self.servSock.raw_sock.accept()
        sockWrap = SockWrapper(raw_sock=sock,inetAddr=addr)
        #get id from client
        sockWrap.id = sockWrap.recvInt()
        #store in clients list
        self.clients.append(sockWrap)

    def recoverTCP(self,sock,timeOut):
        self.servSock.raw_sock.settimeout(timeOut)
        prevClientId = sock.id
        try:
            self.__registerNewClient()
        except OSError as e:
            #disable timeout
            self.servSock.raw_sock.settimeout(None)
            raise 
        #compare prev and cur clients id's, may be the same client
        if sock.id != prevClientId:
            raise OSError("new client has connected")
        return sock

    def recoverUDP(self):
        pass
    
    def queryFactory(self,sock):
        cmdMsg = sock.recvMsg()
        try:
            str_cmd,args = Query.parseCommand(cmdMsg)
        except QueryError as e:
            sock.sendMsg(e.args[0])
            raise
        return Query(sock,self.udpServSock,self.recoverTCP,self.recoverUDP,str_cmd,args)

    def clientAliveCheck(self,query):
        if not query.clientIsAlive:
            try:
                self.clients.remove(query.tcpSock)
            except ValueError:
                pass
    def clientsMultiplexing(self):
        readable = []
        queries = []
        while True:
            #add clients to checkable select list 
            readable = [sock.raw_sock for sock in self.clients]
            #add server tcp socket
            readable.append(self.servSock.raw_sock)
            #clear executed requests
            queries = [query for query in queries if query.status != QueryStatus.Complete and query.clientIsAlive == True]
            timeout = 0 if queries else None 
            try:
                readable,writable,exceptional = select.select(readable,[],[],timeout)          
            except OSError:
                continue
            #if new client try to connect
            if self.servSock.raw_sock in readable:
                self.__registerNewClient()
            for sock in self.clients:
                if sock.raw_sock in readable:
                    try:
                        queries.append( self.queryFactory(sock) )
                    except (QueryError,OSError):
                        continue 
            for query in queries:
                query.execute()
                self.clientAliveCheck(query)


class Query:

    def __init__(self,tcpSock,udpSock,recoverTCP,recoverUDP,str_cmd,args):
        self.status = QueryStatus.Actual
        self.fileWorker = None
        self.recoverTCP = recoverTCP
        self.recoverUDP = recoverUDP
        self.tcpSock = tcpSock
        self.udpSock = udpSock
        self.str_cmd = str_cmd
        self.args = args
        self.clientIsAlive = True
        #for UDP
        self.udpClientAddr = None
   
    @classmethod
    def parseCommand(cls,cmd_msg):
        #check command format
        regExp = re.compile("[A-Za-z0-9_]+ *.*")
        if regExp.match(cmd_msg) is None:
            raise QueryError("invalid command format \"" + cmd_msg + "\"")
        #find pure command
        commandRegEx = re.compile("[A-Za-z0-9_]+")
        #match() Determine if the RE matches at the beginning of the string.
        matchObj = commandRegEx.match(cmd_msg)
        if(matchObj == None):
            #there is no suitable command
            raise QueryError('there is no such command')
        #group()	Return the string matched by the RE
        str_cmd = matchObj.group()
        if not hasattr(cls,str_cmd):
            raise QueryError('command is not implemented')
        #end() Return the ending position of the match
        cmdEndPos = matchObj.end()
        #cut finding command from the commandMes
        args = cmd_msg[cmdEndPos:]
        #cut spaces after command
        args = args.lstrip()
        return (str_cmd,args)
   
    def execute(self):
        try:
            func = getattr(self,self.str_cmd)
            func()
        except AttributeError as e:
            print(e)
            self.tcpSock.sendMsg(e.args[0])
            self.status = QueryStatus.Complete
         
    def echo(self):
        self.tcpSock.sendMsg(self.args)
        self.status = QueryStatus.Complete

    def time(self):
        self.tcpSock.sendMsg(time.asctime())
        self.status = QueryStatus.Complete

    def quit(self):
        self.tcpSock.raw_sock.shutdown(SHUT_RDWR)
        self.tcpSock.raw_sock.close()
        self.status = QueryStatus.Complete
        self.clientIsAlive = False

    def completeState(self,clientMsg):
        self.status = QueryStatus.Complete
        self.tcpSock.sendMsg(clientMsg)

    def restoreClientAddrForUDP(self):
        self.udpSock.clientAddr = self.udpClientAddr

    def getClientAddr(self):
        self.udpSock.recvInt()
        self.udpClientAddr = self.udpSock.clientAddr

    def downloadStateMachine(self,sock,fileInfoRoutine,packetsRoutine,recoverRoutine,clientMsg):
       #transfer init
        if self.status == QueryStatus.Actual:
            self.fileWorker =  FileWorker(sock,self.args,recoverRoutine)
            try:
                #get udp client addr
                if sock.proto == IPPROTO_UDP:
                    self.getClientAddr()
                fileInfoRoutine(self.fileWorker)
                self.status = QueryStatus.InPorgress
            except FileWorkerError as e:
                self.clientIsAlive = False
                self.completeState(e.args[0])
       #packets
        elif self.status == QueryStatus.InPorgress:
            try:
                if sock.proto == IPPROTO_UDP:
                    self.restoreClientAddrForUDP()
                packetsRoutine(self.fileWorker)
                if self.fileWorker.file.closed:
                    #download complete
                    self.completeState(clientMsg)
            except FileWorkerError as e:
                #download error
                self.clientIsAlive = False
                self.completeState(e.args[0])

    def download(self):
        self.downloadStateMachine(self.tcpSock,FileWorker.sendFileInfo,FileWorker.sendPacketsTCP,self.recoverTCP,'file downloaded')
       
    def upload(self):
        self.downloadStateMachine(self.tcpSock,FileWorker.recvFileInfo,FileWorker.recvPacketsTCP,self.recoverTCP,'file uploaded')
    
    def download_udp(self):
        self.downloadStateMachine(self.udpSock,FileWorker.sendFileInfo,FileWorker.sendPacketsUDP,None,'file downloaded')
        
            
if __name__ == "__main__":  
    server = TCPServer("192.168.1.2","6000")
    server.clientsMultiplexing()
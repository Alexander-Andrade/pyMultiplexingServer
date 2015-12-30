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
    '''
    def __clientCommandsHandling(self):
        while True:
            try:
                message = self.talksock.recvMsg()
                if len(message) == 0:
                    break
                regExp = re.compile("[A-Za-z0-9_]+ *.*")
                if regExp.match(message) is None:
                    self.talksock.sendMsg("invalid command format \"" + message + "\"")
                    continue
                if not self.catchCommand(message):
                    self.talksock.sendMsg("unknown command")
                #quit
                if message.find("quit") != -1:
                    break
            except FileWorkerError as e:
                #can work with the same client
                print(e)
                
            except (OSError,FileWorkerError):
                #wait for the new client
                break

    '''

    def queryFactory(self,sock):
        cmdMsg = sock.recvMsg()
        str_cmd,args = Query.parseCommand(cmdMsg)
        return Query(self.servSock,sock,self.udpServSock,str_cmd,args)

    def clientsMultiplexing(self):
        readable = []
        queries = []
        while True:
            #add clients to checkable select list 
            readable = [sock.raw_sock for sock in self.clients]
            #add server tcp socket
            readable.append(self.servSock.raw_sock)
            timeout = 0 if queries else None 
            try:
                readable,writable,exceptional = select.select(readable,[],[],timeout)          
            except OSError:
                continue
            #if new client try to connect
            if self.servSock.raw_sock in readable:
                self.__registerNewClient()
            #clear executed requests
            queries = [query for query in queries if query.status != QueryStatus.Complete]
            for sock in self.clients:
                if sock.raw_sock in readable:
                    try:
                        queries.append( self.queryFactory(sock) )
                    except QueryError:
                        continue   
            for query in queries:
                query.execute()


class Query:

    def __init__(self,tcpServSock,tcpSock,udpSock,str_cmd,args):
        self.status = QueryStatus.Actual
        self.fileWorker = None
        self.tcpServSock = tcpServSock
        self.tcpSock = tcpSock
        self.udpSock = udpSock
        self.str_cmd = str_cmd
        self.args = args

   
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
         
    def echo(self):
        self.tcpSock.sendMsg(self.args)
        self.status = QueryStatus.Complete

    def time(self):
        self.tcpSock.sendMsg(time.asctime())
        self.status = QueryStatus.Complete

    def quit(self):
        self.tcpSock.raw_sock.shutdown(SHUT_RDWR)
        self.tcpSock.raw_sock.close()
        self.tcpSock.raw_sock = None
        self.status = QueryStatus.Complete

    def completeState(self,clientMsg):
        self.status = QueryStatus.Complete
        self.tcpSock.sendMsg(clientMsg)

    def downloadStateMachine(self,fileInfoRoutine,packetsRoutine,clientMsg):
       #transfer init
        if self.status == QueryStatus.Actual:
            self.fileWorker =  FileWorker(self.tcpSock,self.args,self.recoverTCP)
            try:
                fileInfoRoutine(self.fileWorker)
                self.status = QueryStatus.InPorgress
            except FileWorkerError as e:
                self.completeState(e)
       #packets
        elif self.status == QueryStatus.InPorgress:
            try:
                packetsRoutine(self.fileWorker)
                if self.fileWorker.file.closed:
                    #download complete
                    self.completeState(clientMsg)
            except FileWorkerError as e:
                #download error
                self.completeState(e)

    def download(self):
        self.downloadStateMachine(FileWorker.sendFileInfo,FileWorker.sendPacketsTCP,'file downloaded')
       
    def upload(self):
        self.downloadStateMachine(FileWorker.recvFileInfo,FileWorker.recvPacketsTCP,'file uploaded')
          
    def recoverTCP(self,timeOut):
        self.tcpServSock.raw_sock.settimeout(timeOut)
        prevClientId = self.tcpSock.id
        try:
            self.__registerNewClient()
        except OSError as e:
            #disable timeout
            self.tcpServSock.raw_sock.settimeout(None)
            raise 
        #compare prev and cur clients id's, may be the same client
        if self.tcpSock.id != prevClientId:
            raise OSError("new client has connected")
        return self.tcpSock

    def recoverUDP(self):
        pass

    import zlib
if __name__ == "__main__":  
    server = TCPServer("192.168.1.2","6000")
    server.clientsMultiplexing()
from SocketWrapper import*
import os
import io
import sys
class FileWorkerError(Exception):
    pass
class FileWorkerCritError(Exception):
    pass
  
class FileWorker:
    

    def __init__(self,sockWrapper,recoveryFunc,bufferSize,timeOut):
        self.timeOut = timeOut
        self.bufferSize = bufferSize
        self.sock = sockWrapper
        self.fileLen = 0
        self.file = None
        self.filePos = 0
        self.loadingPercent = 0
        self.recoveryFunc = recoveryFunc
    

    def outFileInfo(self):
        #print file name
        print("filename: ",end='',flush=True)
        print(self.fileName,flush=True)
        #file size
        print("file size: ",end='',flush=True)
        print(self.fileLen,flush=True)
        sys.stdout.flush()
    

    def percentsOfLoading(self,bytesWrite):
        return int((float(bytesWrite) / self.fileLen) * 100)

    def actualizeAndshowPercents(self,percent,milestone,placeholder):
        #skip zeros
        if percent == 0: return
        i = self.loadingPercent
        if i == 0: i += 1
        for i in range(i,percent):
            if i % milestone == 0:
                print(i,flush=True)
            else:
                print(placeholder,end='',flush=True)
        if percent == 100:
            print(percent,flush=True)
        self.loadingPercent = percent 


    def send(self,fileName):
        self.fileName = fileName
        if not os.path.exists(fileName):
            self.sock.sendRefuse() 
            raise FileWorkerError("file does not exist")
        try:
            #binary mode
            self.file = open(fileName,'rb')
        except OSError:
            #say to receiver that can't open the file
            self.sock.sendRefuse()
            raise FileWorkerError("can't open the file")
        self.sock.sendConfirm()
        self.sock.setSendBufferSize(self.bufferSize)
        #real system buffer size can differ
        self.bufferSize = self.sock.getSendBufferSize()
        #file size in bytes
        self.fileLen = os.path.getsize(fileName)
        #send hint configs to the receiver
        try:
            self.sock.sendInt(self.bufferSize)
            self.sock.sendInt(self.timeOut)
            self.sock.sendInt(self.fileLen)
        except OSError:
            self.file.close()
            raise FileWorkerCritError("can't send file metadata")
        self.outFileInfo()
        #file transfer
        try:
            while True:
                try:
                    data = self.file.read(self.bufferSize)
                    #if eof
                    if not data:
                        self.sock.setReceiveTimeout(self.timeOut)
                        #receiver acknowledge received data size
                        receiverPos = self.sock.recvInt()
                        #return socket into blocking mode
                        self.sock.disableReceiveTimeout()
                        if receiverPos == self.filePos:
                            break
                        else:
                            raise OSError("fail to transfer file")
                    #send data portion
                    #error will rase OSError 
                    self.filePos += len(data)
                    self.actualizeAndshowPercents(self.percentsOfLoading(self.filePos),20,'.') 
                    self.sock.send(data)
                except OSError as e:
                    #file transfer reconnection
                    self.senderRecovers()
        except FileWorkerCritError:
            raise
        finally:
            self.sock.disableReceiveTimeout()
            self.file.close() 
         
            
    def senderRecovers(self):
        try:
            self.sock = self.recoveryFunc(self.timeOut << 1)
        except OSError as e:
            raise FileWorkerCritError(e)
        self.sock.setSendBufferSize(self.bufferSize)
        #get file position to send from
        self.sock.setReceiveTimeout(self.timeOut)
        self.filePos = self.sock.recvInt()
        #remove timeout
        self.sock.disableReceiveTimeout()
        #set file position to read from
        self.file.seek(self.filePos) 

    def readOobData(self):
        try:#if there is some OOB data
            #OOB data (urgent)
            self.sock.raw_sock.setblocking(False)
            self.percent = int.from_bytes(self.sock.recv(1,MSG_OOB),byteorder='big')
            #print(percent)
        except OSError:
            pass
        finally:
            self.sock.raw_sock.setblocking(True)

    def receive(self,fileName):
        self.fileName = fileName
        #set timeout on receive op,to avoid program freezing
        self.sock.setReceiveTimeout(self.timeOut)
        #waiting for checking file existance from transiving side
        if not self.sock.recvAck():
            raise FileWorkerError("there is no such file")
        try:
            self.file = open(fileName,"wb")
        except OSError:
            raise FileWorkerError("can't create the file")
        #get hints configs from the transmitter
        try:
            self.bufferSize = self.sock.recvInt()
            self.timeOut = self.sock.recvInt()
            self.fileLen = self.sock.recvInt()
        except OSError:
            self.file.close()
            raise FileWorkerCritError("can't receive file metadata")
        self.outFileInfo()
        try:
            while True:
                try:
                    #self.readOobData()
                    #usual data
                    '''
                    rest = self.fileLen - self.filePos
                    recvSize = rest if rest < self.bufferSize else (self.bufferSize - 1)
                    data = self.sock.receive(recvSize)
                    '''
                    data = self.sock.recv(self.bufferSize)
                    self.file.write(data)
                    self.filePos += len(data)
                    self.actualizeAndshowPercents(self.percentsOfLoading(self.filePos),20,'.')
                    if self.filePos == self.fileLen:
                        #send ack to end the file transmittion
                        self.sock.sendInt(self.filePos)
                        break
                except OSError as e:
                     #file transfer reconnection
                    self.receiverRecovers()
        except FileWorkerCritError:
            raise
        finally:
            self.sock.disableReceiveTimeout()
            self.file.close()


    def receiverRecovers(self):
        try:
            self.sock = self.recoveryFunc(self.timeOut << 1)
        except OSError as e:
            raise FileWorkerCritError(e)
        #gives file position to start from
        self.sock.sendInt(self.filePos)
        #timeout on receive op
        self.sock.setReceiveTimeOut(self.timeOut)


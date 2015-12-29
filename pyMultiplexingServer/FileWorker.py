from SocketWrapper import*
import os
import io
import sys
import hashlib #adler32,md5
import zlib #crc32,adler32


class FileWorkerError(Exception):
    pass
class FileWorkerCritError(Exception):
    pass
  
class FileWorker:
    

    def __init__(self,sockWrapper,fileName,recoveryFunc,nPacks=6,bufferSize = 1024,timeOut=30):
        self.timeOut = timeOut
        #packs throw one transfer
        self.nPacks = nPacks
        self.sock = sockWrapper
        self.bufferSize = bufferSize
        self.fileLen = 0
        self.fileName = fileName
        self.file = None
        self.filePos = 0
        self.loadingPercent = 0
        self.recoveryFunc = recoveryFunc
        #number of transfer attempts
        self.nAttempts = 3

    def calcFileMD5(self,dataSize=1024):
        actualfPos =  self.file.tell()
        #set to the file beg
        self.file.seek(0,0)
        #read data portion
        md5 = hashlib.md5()
        while True:
            data = self.file.read(dataSize)
            if not data:
                break
            md5.update(data)
        #set old file pos
        self.file.seek(0,actualfPos)
        return md5

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

    def onEndTranser(self):
        self.sock.disableReceiveTimeout()
        self.file.close()

    def sendFileInfo(self):
        if not os.path.exists(fileName):
            self.sock.sendRefuse() 
            raise FileWorkerCritError("file does not exist")
        try:
            #binary mode
            self.file = open(self.fileName,'rb')
        except OSError:
            #say to receiver that can't open the file
            self.sock.sendRefuse()
            raise FileWorkerCritError("can't open the file")
        self.sock.sendConfirm()
        self.fileLen = os.path.getsize(fileName)
        self.outFileInfo()
        self.sock.setReceiveTimeout(self.timeOut)
        goodChecksum = False  
        try:
            for i in range(self.nAttempts):
                try:
                    #send hint configs to the receiver
                    self.sock.sendInt(self.bufferSize)
                    self.sock.sendInt(self.timeOut)
                    self.sock.sendInt(self.fileLen)
                    #handshake
                    #calculate checksum
                    local_checksum = zlib.crc32(self.bufferSize.to_bytes(codeSize, byteorder='big') + self.timeOut.to_bytes(codeSize, byteorder='big') + self.fileLen.to_bytes(codeSize, byteorder='big'))
                    codeSize = len(local_checksum)    
                    peer_checksum = self.sock.recv(codeSize)
                    self.sock.send(local_checksum)
                    if peer_checksum == local_checksum:
                        goodChecksum = True
                        break
                except OSError:
                    self.senderRecovers()
            #if not goodChecksum:
            if not goodChecksum:
                raise FileWorkerCritError('attempts are exhausted')
        except FileWorkerCritError:
            self.onEndTranser()
            raise

    def sendPacketsTCP(self):
        #file transfer
        try:
            for pack in range(self.nPacks):
                try:
                    data = self.file.read(self.bufferSize)
                    #if eof
                    if not data:
                        #calc local md5
                        local_md5 = self.calcFileMD5()
                        peer_md5 = self.sock.recv(localMD5.digest_size)
                        if local_md5 == peer_md5:
                            self.onEndTranser()
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
            self.onEndTranser()
            raise           
         
            
    def senderRecovers(self):
        try:
            self.sock = self.recoveryFunc(self.timeOut << 1)
        except OSError as e:
            raise FileWorkerCritError(e)
        #get file position to send from
        self.sock.setReceiveTimeout(self.timeOut)
        self.filePos = self.sock.recvInt()
        #set file position to read from
        self.file.seek(self.filePos) 

    def recvFileInfo(self):
        #set timeout on receive op,to avoid program freezing
        self.sock.setReceiveTimeout(self.timeOut)
        #waiting for checking file existance from transiving side
        if not self.sock.recvAck():
            raise FileWorkerError("there is no such file")
        try:
            self.file = open(self.fileName,"wb")
        except OSError:
            raise FileWorkerError("can't create the file")
        #get hints configs from the transmitter
        goodChecksum = False
        try:
            for i in range(self.nAttempts):
                try:
                    self.bufferSize = self.sock.recvInt()
                    self.timeOut = self.sock.recvInt()
                    self.fileLen = self.sock.recvInt()
                    #calc crc32
                    local_checksum = zlib.crc32(self.bufferSize.to_bytes(codeSize, byteorder='big') + self.timeOut.to_bytes(codeSize, byteorder='big') + self.fileLen.to_bytes(codeSize, byteorder='big'))
                    #handshake
                    codeSize = len(local_checksum)
                    self.sock.send(local_checksum)
                    peer_checksum = self.sock.recv(codeSize)
                    if peer_checksum == local_checksum:
                        goodChecksum = True
                        break
                except OSError:
                    self.receiverRecovers()
            if not goodChecksum:
                raise FileWorkerCritError('attempts are exhausted')
        except FileWorkerCritError:
            self.onEndTranser()
            raise
        self.outFileInfo()

    def recvPacketsTCP(self,fileName):
        try:
            for pack in range(self.nPacks):
                try:
                    data = self.sock.recv(self.bufferSize)
                    self.file.write(data)
                    self.filePos += len(data)
                    self.actualizeAndshowPercents(self.percentsOfLoading(self.filePos),20,'.')
                    if self.filePos == self.fileLen:
                        #calc local md5
                        local_md5 = self.calcFileMD5()
                        #handshake
                        self.sock.send(local_md5)
                        peer_md5 = self.sock.recv(localMD5.digest_size)
                        if local_md5 == peer_md5:
                            self.onEndTranser()
                            break
                        else:
                            raise FileWorkerCritError('wrong md5')    
                except OSError as e:
                     #file transfer reconnection
                    self.receiverRecovers()
        except FileWorkerCritError:
            self.onEndTranser()
            raise     


    def receiverRecovers(self):
        try:
            self.sock = self.recoveryFunc(self.timeOut << 1)
        except OSError as e:
            raise FileWorkerCritError(e)
        #gives file position to start from
        self.sock.sendInt(self.filePos)
        #timeout on receive op
        self.sock.setReceiveTimeOut(self.timeOut)


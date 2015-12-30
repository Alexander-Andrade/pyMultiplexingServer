from SocketWrapper import*
import os
import io
import sys
import hashlib #adler32,md5
import zlib #crc32,adler32

class FileWorkerError(Exception):
    pass

def calcFileMD5(fileName,dataSize=1024):
    with open(fileName,'rb') as file:
        #read data portion
        md5 = hashlib.md5()
        while True:
            data = file.read(dataSize)
            if not data:
               break
            md5.update(data)   
    return (md5.digest(),md5.digest_size)
  
def crcFromIntList(obj_list):
    crc_size = 4
    #make from list bytes
    byte_obj_list = [obj.to_bytes(crc_size, byteorder='big') for obj in obj_list]
    join_bytes = b''.join(byte_obj_list)
    #calc crc32
    return zlib.crc32(join_bytes)
  
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

    def crcHandShake(self,arglist,toggle):
        local_checksum = crcFromIntList(arglist)
        peer_checksum = 0
        #handshake
        if toggle:#sending side
            peer_checksum = self.sock.recvInt()
            self.sock.sendInt(local_checksum)
        else:#receiving side
            self.sock.sendInt(local_checksum)
            peer_checksum = self.sock.recvInt()
        if peer_checksum != local_checksum:
            raise FileWorkerError('wrong crc')

    
    def fileMd5HandShake(self,toggle):
        #calc local md5
        local_md5,md5_size = calcFileMD5(self.fileName)
        peer_md5 = b''
        if toggle:
            peer_md5 = self.sock.recv(md5_size)
            self.sock.send(local_md5)
        else:
            self.sock.send(local_md5)
            peer_md5 = self.sock.recv(md5_size)
        if local_md5 != peer_md5:
            raise OSError("fail to transfer file")

    def sendFileInfo(self):
        if not os.path.exists(self.fileName):
            self.sock.sendRefuse() 
            raise FileWorkerError("file does not exist")
        try:
            #binary mode
            self.file = open(self.fileName,'rb')
        except OSError:
            #say to receiver that can't open the file
            self.sock.sendRefuse()
            raise FileWorkerError("can't open the file")
        self.sock.sendConfirm()
        self.fileLen = os.path.getsize(self.fileName)
        self.outFileInfo()
        self.sock.setReceiveTimeout(self.timeOut) 
        try:
            for i in range(self.nAttempts):
                try:
                    #send hint configs to the receiver
                    self.sock.sendInt(self.bufferSize)
                    self.sock.sendInt(self.timeOut)
                    self.sock.sendInt(self.fileLen)
                    #handshake
                    self.crcHandShake([self.bufferSize,self.timeOut,self.fileLen],True)
                    break
                except OSError:
                    self.senderRecovers()
                except FileWorkerError:
                    if i == self.nAttempts - 1:
                        raise
                    continue
        except FileWorkerError:
            self.onEndTranser()

    def sendPacketsTCP(self):
        #file transfer
        try:
            for pack in range(self.nPacks):
                try:
                    data = self.file.read(self.bufferSize)
                    #if eof
                    if not data:
                        self.fileMd5HandShake(True)
                        self.onEndTranser()
                        break
                    self.filePos += len(data)
                    self.actualizeAndshowPercents(self.percentsOfLoading(self.filePos),20,'.') 
                    self.sock.send(data)
                except OSError as e:
                    #file transfer reconnection
                    self.senderRecovers()
        except FileWorkerError:
            self.onEndTranser()
            raise           
         
            
    def senderRecovers(self):
        try:
            self.sock = self.recoveryFunc(self.timeOut << 1)
        except OSError as e:
            raise FileWorkerError(e)
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
        try:
            for i in range(self.nAttempts):
                try:
                    self.bufferSize = self.sock.recvInt()
                    self.timeOut = self.sock.recvInt()
                    self.fileLen = self.sock.recvInt()
                    self.crcHandShake([self.bufferSize,self.timeOut,self.fileLen],False)
                    break
                except OSError:
                    self.receiverRecovers()
                except FileWorkerError:
                    #wrong crc
                    if i == self.nAttempts - 1:
                        raise
                    continue
        except FileWorkerError:
            self.onEndTranser()
        self.outFileInfo()

    def recvPacketsTCP(self):
        try:
            for pack in range(self.nPacks):
                try:
                    data = self.sock.recv(self.bufferSize)
                    self.file.write(data)
                    self.filePos += len(data)
                    self.actualizeAndshowPercents(self.percentsOfLoading(self.filePos),20,'.')
                    if self.filePos == self.fileLen:
                        self.file.flush()
                        self.fileMd5HandShake(False)
                        self.onEndTranser()
                        break    
                except OSError as e:
                     #file transfer reconnection
                    self.receiverRecovers()
        except FileWorkerError:
            self.onEndTranser()
            raise     


    def receiverRecovers(self):
        try:
            self.sock = self.recoveryFunc(self.timeOut << 1)
        except OSError as e:
            raise FileWorkerError(e)
        #gives file position to start from
        self.sock.sendInt(self.filePos)
        #timeout on receive op
        self.sock.setReceiveTimeOut(self.timeOut)


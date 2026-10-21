"""Small dependency-free Source RCON client for Minecraft Java dedicated servers."""
from __future__ import annotations

from dataclasses import dataclass
import socket
import struct


class RconError(RuntimeError):
    pass


@dataclass
class Rcon:
    host: str
    port: int
    password: str
    timeout: float = 8.0
    sock: socket.socket | None = None

    def __enter__(self) -> "Rcon":
        if not self.password:
            raise RconError("MCBH_RCON_PASSWORD is required")
        self.sock = socket.create_connection((self.host,self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self._send(1001,3,self.password)
        for _ in range(4):
            packet_id,kind,_ = self._recv()
            if packet_id == -1:
                raise RconError("RCON authentication rejected")
            if packet_id == 1001 and kind == 2:
                return self
        raise RconError("No RCON authentication response")

    def __exit__(self,*args:object) -> None:
        if self.sock:
            self.sock.close()
            self.sock=None

    def _read(self,length:int)->bytes:
        assert self.sock is not None
        output=b""
        while len(output)<length:
            part=self.sock.recv(length-len(output))
            if not part:
                raise RconError("RCON connection closed")
            output+=part
        return output

    def _send(self,request_id:int,kind:int,body:str)->None:
        assert self.sock is not None
        data=struct.pack("<ii",request_id,kind)+body.encode("utf-8")+b"\0\0"
        self.sock.sendall(struct.pack("<i",len(data))+data)

    def _recv(self)->tuple[int,int,str]:
        size=struct.unpack("<i",self._read(4))[0]
        if not 10<=size<=1_048_576:
            raise RconError("Invalid RCON packet size")
        packet=self._read(size)
        request_id,kind=struct.unpack("<ii",packet[:8])
        if packet[-2:] != b"\0\0":
            raise RconError("Invalid RCON packet terminator")
        return request_id,kind,packet[8:-2].decode("utf-8","replace")

    def command(self,command:str)->str:
        if not command or "\n" in command or "\r" in command or "\0" in command:
            raise RconError("Invalid RCON command")
        self._send(1002,2,command.lstrip("/"))
        for _ in range(3):
            request_id,kind,message=self._recv()
            if request_id == 1002 and kind == 0:
                return message
            if request_id == -1:
                raise RconError("RCON command denied")
        raise RconError("Unexpected RCON response")

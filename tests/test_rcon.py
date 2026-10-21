import socket
import struct
import threading

import pytest

from mcbh.rcon import Rcon, RconError


def packet(request_id, kind, body):
    payload=struct.pack('<ii',request_id,kind)+body.encode()+b'\0\0'
    return struct.pack('<i',len(payload))+payload


def read_exact(s, n):
    out=b''
    while len(out)<n:
        piece=s.recv(n-len(out))
        if not piece:
            raise EOFError()
        out+=piece
    return out


def fake_server(sock):
    conn,_=sock.accept()
    with conn:
        size=struct.unpack('<i',read_exact(conn,4))[0]
        auth=read_exact(conn,size)
        assert auth[8:-2]==b'password'
        conn.sendall(packet(1001,0,'')+packet(1001,2,''))
        size=struct.unpack('<i',read_exact(conn,4))[0]
        command=read_exact(conn,size)
        assert command[8:-2]==b'list'
        conn.sendall(packet(1002,0,'There are 0 of a max of 20 players online'))


def test_rcon_auth_and_command():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1',0))
        listener.listen(1)
        thread=threading.Thread(target=fake_server,args=(listener,),daemon=True)
        thread.start()
        with Rcon('127.0.0.1',listener.getsockname()[1],'password') as client:
            assert '0 of a max' in client.command('list')
            with pytest.raises(RconError,match='Invalid RCON command'):
                client.command('list\nstop')
        thread.join(timeout=3)
        assert not thread.is_alive()

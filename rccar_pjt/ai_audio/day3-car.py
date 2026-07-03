# SSAFY 8 embedded proj.
# day 3. RC Vehicle (수정 및 디버깅 보완본)

'''
- AR goggle의 마이크를 통해 음성으로 지령하여 차량을 제어할 수 있도록 한다.
- Websocket proocol을 구현한 python websocket modules를 사용하여 goggle과 차량간에 통신한다.
- 앞서 구현한 8개 명령어 (앞으로, 뒤로, 정지, 빠르게, 느리게, 오른쪽, 왼쪽 중앙)는 기본적으로 사용할 수 있도록 한다. 
- 콘솔에서 프로그램을 실행시키지 않아도 전원을 켜면 곧바로 작동하여 독립된 장치로 기능할 수 있도록 한다. 
- 본인의 아이디어를 더해 발전시켜 완성한다.
'''

# 모듈 로드
from Raspi_MotorHAT import Raspi_MotorHAT, Raspi_DCMotor
import asyncio
import websockets
import traceback  # 에러 원인을 상세히 추적하기 위해 추가

# 모터 초기설정
try:
    mh = Raspi_MotorHAT(addr = 0x6f)
    motor1 = mh.getMotor(2) # M1단자에 모터연결
    speed = 125 # 모터 속도 0~255
    motor1.setSpeed(speed)

    # 서보 초기설정
    servo = mh._pwm
    servo.setPWMFreq(60)
except Exception as e:
    print("\n⚠️ 모터 드라이버(I2C) 초기화 실패! 연결 상태나 I2C 활성화 여부를 확인하세요.")
    traceback.print_exc()

servoCH = 0 # 서보 연결된 핀
SERVO_PULSE_MAX = 614   # 서보 작동 범위
SERVO_PULSE_MIN = 200

# 웹소켓 서버(차량) ip (라즈베리파이 자신의 IP가 맞는지 확인 필요)
ServerIP = '0.0.0.0'
WebsocketPort = 7890

# 앞으로
def go():
    print("[Action] 전진 (FORWARD)")
    motor1.run(Raspi_MotorHAT.FORWARD)

# 뒤로
def back():
    print("[Action] 후진 (BACKWARD)")
    motor1.run(Raspi_MotorHAT.BACKWARD)

# 모터 정지
def stop():
    print("[Action] 정지 (RELEASE)")
    motor1.run(Raspi_MotorHAT.RELEASE)

# 빠르게
def speed_up():
    global speed
    speed = 255 if speed >= 235 else speed + 20 # 최대 255, 20단위로 증가
    print(f"[Action] 속도 증가 ➔ {speed}")
    motor1.setSpeed(speed)

# 느리게
def speed_down():
    global speed
    speed = 0 if speed <= 20 else speed - 20 # 최하 0
    print(f"[Action] 속도 감소 ➔ {speed}")
    motor1.setSpeed(speed)

# 각도만큼 핸들 틀기
def steer(angle = 0):   
    if angle <= -60:
        angle = -60
    if angle >= 60:
        angle = 60
    pulse_time = SERVO_PULSE_MIN + (SERVO_PULSE_MAX - SERVO_PULSE_MIN) // 180 * (angle + 90) # angle = -90°~ +90° 사이의 값. 비례해서 pulse_time이 정해짐

    servo.setPWM(servoCH, 0, pulse_time)

# 우회전
def steer_right():
    print("[Action] 조향 우회전")
    steer(30)

# 좌회전
def steer_left():
    print("[Action] 조향 좌회전")
    steer(-30)

# 핸들 중앙
def steer_center():
    print("[Action] 조향 정중앙")
    steer(0)

# 클라이언트로부터 받을 수 있는 명령과 대응하는 function
command = ['앞으로', '뒤로', '정지', '빠르게', '느리게', '오른쪽', '왼쪽', '중앙']
func = [go, back, stop, speed_up, speed_down, steer_right, steer_left, steer_center]

async def voice_drive(websocket, path=None): # [보안] 일부 websockets 버전 호환성을 위해 path=None 처리
    print(f"🔗 클라이언트 연결됨! (Client IP: {websocket.remote_address})")
    try:
        loop = asyncio.get_running_loop()   # asyncio 이벤트루프

        while True:
            # 클라이언트로부터 메시지 받음
            message = await websocket.recv()
            print(f'📩 수신된 메시지: {message}')
            
            # 메시지에 해당하는 index의 func 실행
            if message in command:
                print(f'✅ 매칭된 명령어 발견: [{message}] 실행합니다.')
                # run_in_executor() 사용해 별도 스레드에서 비동기적으로 함수 실행
                await loop.run_in_executor(None, func[command.index(message)]) 
                response = 'OK'
            else:
                print(f'❌ 유효하지 않은 명령어: {message}')
                response = 'not a command'
                
            # 응답 보냄
            await websocket.send(response)
    
    except websockets.ConnectionClosed:
        print('🔌 클라이언트와 웹소켓 연결이 끊어졌습니다.')
    except Exception as e:
        print('⚠️ 통신 중 예외 발생:')
        traceback.print_exc()

async def main():
    try:
        # websocket 서버 작동
        print(f"🚀 웹소켓 서버를 시작합니다... (Host: {ServerIP}, Port: {WebsocketPort})")
        server = await websockets.serve(voice_drive, host = ServerIP, port = WebsocketPort)
        print('✨ Server Ready! 클라이언트 지령을 기다리는 중입니다...')
        await server.wait_closed()

    except KeyboardInterrupt:
        print('\n🛑 사용자의 요청(Ctrl+C)으로 안전하게 서버를 종료합니다...')
    except Exception as e:
        print('\n❌ 서버 구동 중 치명적인 오류가 발생했습니다:')
        traceback.print_exc()  # 기존의 '확인되지 않은 오류' 대신 상세 로그 출력
    finally:
        print('🧹 모터 전원을 해제하고 프로그램을 완전히 종료합니다.')
        try:
            motor1.run(Raspi_MotorHAT.RELEASE)  # 종료시 모터 멈춤
        except:
            pass
    
if __name__ == '__main__':
    asyncio.run(main())

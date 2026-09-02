/*
 * motorhat.h
 *
 *  Created on: 2024. 5. 14.
 *      Author: SSAFY
 *
 *  PCA9685 레지스터 정의(__MODE1 · __PRESCALE · __LED0_ON_L 등)와 PWM 제어 API 는
 *  Adafruit Motor HAT Python 라이브러리를 C 로 옮긴 것이다.
 *  https://github.com/adafruit/Adafruit-Motor-HAT-Python-Library
 *  Copyright (c) Adafruit Industries. MIT License.
 *  ("MIT license, all text above must be included in any redistribution")
 *
 *  이 저장소의 변경 사항: I2C 백엔드를 Renesas FSP(R_IIC_MASTER_*)로 이식하고
 *  전송 완료를 콜백으로 동기화하도록 수정.
 */

#ifndef MOTORHAT_H_
#define MOTORHAT_H_
#include "hal_data.h"

// motorhat.h
#define __MODE1              0x00
#define __MODE2              0x01
#define __SUBADR1            0x02
#define __SUBADR2            0x03
#define __SUBADR3            0x04
#define __PRESCALE           0xFE
#define __LED0_ON_L          0x06
#define __LED0_ON_H          0x07
#define __LED0_OFF_L         0x08
#define __LED0_OFF_H         0x09
#define __ALL_LED_ON_L       0xFA
#define __ALL_LED_ON_H       0xFB
#define __ALL_LED_OFF_L      0xFC
#define __ALL_LED_OFF_H      0xFD
#define __RESTART            0x80
#define __SLEEP              0x10
#define __ALLCALL            0x01
#define __INVRT              0x10
#define __OUTDRV             0x04

extern int PWMpin;
extern int IN1pin;
extern int IN2pin;
extern volatile i2c_master_event_t g_iic_callback_event;


void iic_callback(i2c_master_callback_args_t *p_args);
uint8_t read_byte_data(uint8_t reg);
void write_byte_data(int reg, int val);
void write8( int reg, int value );
uint8_t readU8(uint8_t reg);
void setPWM(int channel, int on, int off);
void setAllPWM(int on, int off);
void setPWMFreq(int freq);
void setPin(int pin, int value);
void Forward();
void Backward();
void Release();
void setSpeed(int speed);
void PWM(int addr);
void init(int addr);
void Left();
void Right();
void Mid();

#endif /* MOTORHAT_H_ */

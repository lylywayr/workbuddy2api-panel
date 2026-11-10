// Package xtime 提供与时间相关的、被多个包共用的小工具。
//
// 为什么独立成包：sleepCtx 曾在 server 与 scheduler 各存一份逐字相同的实现
// （server 那份的注释还写着「按等价物口径在消费侧实现」）。两份可取消等待的实现
// 正是「其中一份悄悄丢掉 t.Stop() 而泄漏定时器」的温床，故抽为单一事实来源。
package xtime

import (
	"context"
	"math/rand/v2"
	"time"
)

// SleepCtx 可取消的等待：ctx 取消立即返回 false（客户端断连 / 优雅停机不必等
// 退避睡醒），等满返回 true。d<=0 时立即放行（仅以 ctx 是否仍存活为结果）。
func SleepCtx(ctx context.Context, d time.Duration) bool {
	if d <= 0 {
		return ctx.Err() == nil
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

// JitterSleep 睡 [base, base+max) 的随机时长，模拟真实用户操作的不均匀节奏。
// 反风控用途：固定间隔 / 同刻并发是多账号自动化的时间分布特征，叠加随机
// 抖动后（如账号开工错峰、项间节流叠加、签到账号间隔）行为更接近真人。
// max<=0 时只睡 base（与无抖动旧行为一致，便于测试清零）。不可取消——
// 需要可取消语义的场景用 SleepCtx 自行组合。
func JitterSleep(base, max time.Duration) {
	if max <= 0 {
		time.Sleep(base)
		return
	}
	time.Sleep(base + time.Duration(rand.Int64N(int64(max))))
}

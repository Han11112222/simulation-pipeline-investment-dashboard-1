import streamlit as st
import pandas as pd
import numpy as np
import numpy_financial as npf

# [설정] 페이지 기본
st.set_page_config(page_title="신규배관 경제성 분석 Simulation", layout="wide")

# [함수] 금융 계산 로직 (엑셀 고정형 OCF 방식 적용 -> 감가상각 종료 반영)
def manual_npv(rate, values):
    return sum(v / ((1 + rate) ** i) for i, v in enumerate(values))

def calculate_simulation(sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost, 
                         sim_jeon, sim_basic_rev, rate, tax, dep_period, analysis_period, c_maint, c_adm_jeon, c_adm_m):
    
    # 1. 초기 순투자액 (Year 0)
    net_inv = sim_inv - sim_contrib - sim_other
    
    # 2. 고정 수익/비용 항목 계산
    margin_total = (sim_rev - sim_cost) + sim_basic_rev 
    unit_margin = margin_total / sim_vol if sim_vol > 0 else 0
    cost_sga = (sim_len * c_maint) + (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
    annual_depreciation = sim_inv / dep_period if dep_period > 0 else 0
    
    # 3. 세후 현금흐름(OCF) 산출 (감가상각 종료 연도 반영)
    flows = [-net_inv]
    ocfs = []
    
    for year in range(1, int(analysis_period) + 1):
        current_dep = annual_depreciation if year <= dep_period else 0
        current_ebit = margin_total - cost_sga - current_dep
        current_ni = current_ebit * (1 - tax)
        current_ocf = current_ni + current_dep
        
        flows.append(current_ocf)
        ocfs.append(current_ocf)

    first_ocf = ocfs[0] if len(ocfs) > 0 else 0
    first_ebit = margin_total - cost_sga - annual_depreciation
    
    # [추가] 좀비 배관(가짜 흑자) 판별 및 민감도 분석 로직
    ocf_with_dep = (margin_total - cost_sga - annual_depreciation) * (1 - tax) + annual_depreciation
    ocf_without_dep = (margin_total - cost_sga) * (1 - tax)
    is_zombie = (ocf_with_dep > 0) and (ocf_without_dep < 0)
    
    # 유지비/관리비가 몇 % 오르면 마진(margin_total)을 초과하여 좀비가 되는지 역산
    if cost_sga > 0:
        zombie_threshold_pct = (margin_total / cost_sga - 1) * 100
    else:
        zombie_threshold_pct = float('inf')
    
    # 4. 지표 산출
    npv_val = manual_npv(rate, flows)
    
    irr_val = None
    irr_reason = ""
    
    if net_inv <= 0:
        irr_reason = "초기 순투자비가 0원 이하(보조금/분담금 과다)로 수익률 산출 의미 없음"
    elif all(f <= 0 for f in ocfs): 
        irr_reason = "운영 적자 지속(모든 연도 OCF ≤ 0)으로 투자금 회수 불가"
    else:
        try:
            irr_val = npf.irr(flows)
        except:
            irr_reason = "계산 오류 발생 (현금흐름 부호 변동 없음 등)"
    
    # 5. [수정] 감가상각 종료를 완벽히 반영한 목표 판매량 역산 함수
    def get_req_vol(target_period):
        pvifa_total = (1 - (1 + rate) ** (-target_period)) / rate if rate != 0 else target_period
        pvifa_dep = (1 - (1 + rate) ** (-min(target_period, dep_period))) / rate if rate != 0 else min(target_period, dep_period)
        
        if pvifa_total > 0 and (1 - tax) > 0:
            target_margin_minus_sga = (net_inv - annual_depreciation * tax * pvifa_dep) / (pvifa_total * (1 - tax))
            target_margin = target_margin_minus_sga + cost_sga
            req_v = target_margin / unit_margin if unit_margin > 0 else 0
            return max(0, req_v)
        return 0

    required_vol_30 = get_req_vol(30)
    required_vol_50 = get_req_vol(50)
    
    return {
        "npv": npv_val, "irr": irr_val, "irr_reason": irr_reason, "net_inv": net_inv, 
        "first_ocf": first_ocf, "first_ebit": first_ebit, "sga": cost_sga, 
        "dep": annual_depreciation, "margin": margin_total, "flows": flows, 
        "required_vol_30": required_vol_30, "required_vol_50": required_vol_50,
        "avg_ocf": np.mean(ocfs), "is_zombie": is_zombie,
        "zombie_threshold_pct": zombie_threshold_pct
    }

# --------------------------------------------------------------------------
# [UI] 좌측 사이드바
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 분석 변수")
    st.subheader("📊 분석 기준")
    rate_pct = st.number_input("할인율 (%)", value=6.15, step=0.01, format="%.2f")
    tax_pct = st.number_input("법인세율+주민세율 (%)", value=22.0, step=0.1, format="%.1f")
    
    dep_period = st.number_input("감가상각 연수 (년)", value=30, step=1)
    analysis_period = st.number_input("경제성 분석 연수 (년)", value=30, step=1)
    
    st.subheader("💰 비용 단가 (이전 기준값)")
    c_maint = st.number_input("유지비 (원/m)", value=8222, format="%d")
    c_adm_jeon = st.number_input("관리비 (원/전)", value=6209, format="%d")
    c_adm_m = st.number_input("관리비 (원/m)", value=13605, format="%d")
    
    RATE = rate_pct / 100
    TAX = tax_pct / 100

# --------------------------------------------------------------------------
# [UI] 메인 화면
# --------------------------------------------------------------------------
st.title("🏗️ 신규배관 경제성 분석 Simulation")

# 용도 선택
st.subheader("📌 가스 용도 선택")
usage_type = st.radio(
    "분석할 가스 용도를 선택해 주세요.", 
    ["주택용 (공동주택/단독주택 등)", "기타 (업무용/산업용/영업용 등)"],
    horizontal=True,
    label_visibility="collapsed" 
)
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    st.subheader("1. 투자 정보")
    sim_len = st.number_input("투자 길이 (m)", value=0.0, step=1.0)
    sim_inv = st.number_input("총 공사비 (원)", value=0, format="%d")
    sim_contrib = st.number_input("시설 분담금 (원)", value=0, format="%d")
    sim_other = st.number_input("기타 이익 (보조금, 원)", value=0, format="%d")
    sim_jeon = st.number_input("공급 전수 (전)", value=0, step=1)

with col2:
    st.subheader("2. 수익 정보 (연간)")
    sim_vol = st.number_input("연간 판매량 (MJ)", value=0.0)
    st.caption(f"ℹ️ 환산 부피: **{sim_vol / 42.563:,.0f} ㎥** (적용 열량: 42.563 MJ/㎥)")
    sim_rev = st.number_input("가스 연간 판매액 (원)", value=0, format="%d")
    sim_cost = st.number_input("가스 연간 판매원가 (원)", value=0, format="%d")
    
    st.markdown("---")
    
    if usage_type == "주택용 (공동주택/단독주택 등)":
        st.markdown("**🏡 주택용 기본요금 적용 중**")
        sim_basic_price = st.number_input("월 기본요금 단가 (원/전/월)", value=900, step=10, format="%d")
        sim_basic_rev = sim_basic_price * sim_jeon * 12
        st.info(f"계산된 연간 기본요금 수익: **{sim_basic_rev:,.0f} 원**")
    else:
        st.markdown("**🏢 기타 용도 (기본요금 미적용)**")
        sim_basic_rev = 0
        st.info("해당 용도는 세대별 기본요금이 합산되지 않습니다.")

if "run_sim" not in st.session_state:
    st.session_state.run_sim = False

if st.button("🚀 경제성 분석 실행", type="primary"):
    st.session_state.run_sim = True

if st.session_state.run_sim:
    if sim_vol <= 0 or ((sim_rev - sim_cost) + sim_basic_rev) <= 0:
        st.warning("⚠️ 수익 정보(판매량 및 총 매출마진)를 확인해 주세요. (0보다 커야 합니다)")
    else:
        top_container = st.container()
        
        toggle_placeholder = st.empty()
        with toggle_placeholder:
            long_term_mode = st.toggle("📈 장기분석 (최대 50년) 활성화", value=False)
            
        active_period = 50 if long_term_mode else analysis_period
        
        res = calculate_simulation(sim_len, sim_inv, sim_contrib, sim_other, sim_vol, sim_rev, sim_cost, 
                                   sim_jeon, sim_basic_rev, RATE, TAX, dep_period, active_period, c_maint, c_adm_jeon, c_adm_m)
        
        with top_container:
            st.divider()
            
            if res['is_zombie']:
                st.error("🧟‍♂️ **[주의] 좀비 배관 (가짜 흑자 구간) 감지!**\n\n초기 30년(감가상각 기간) 동안은 세금 혜택으로 인해 장부상 흑자를 띄지만, **감가상각이 종료되는 31년 차부터는 방패가 사라져 순수 운영 적자(마이너스)로 수직 낙하**하여 미래 세대에 엄청난 비용 부담을 주는 배관입니다. 아래 차트 위 **'장기분석 토글'**을 켜서 꺾이는 지점을 직접 확인해 보세요!")
                
            m1, m2, m3 = st.columns(3)
            m1.metric("순현재가치 (NPV)", f"{res['npv']:,.0f} 원")
            
            if res['irr'] is None:
                m2.metric("내부수익률 (IRR)", "계산 불가")
                st.error(f"🚩 **불가 사유**: {res['irr_reason']}")
            else:
                m2.metric("내부수익률 (IRR)", f"{res['irr']*100:.2f} %")
            
            dpp_msg = "회수 가능" if res['npv'] > 0 else "회수 불가 (분석기간 내)"
            m3.metric("할인회수기간 (DPP)", dpp_msg)

            st.subheader("🧐 NPV 산출 사유 분석 (사내 엑셀 기준)")
            st.markdown(f"""
            현재 NPV가 **{res['npv']:,.0f}원**으로 산출된 주요 구조는 다음과 같습니다:
            1. **운영 수익성**: 연간 총 마진({res['margin']:,.0f}원, *기본요금 수익 포함*) 대비 판관비 합계({res['sga']:,.0f}원) 차감
            2. **고정비 부담**: 매년 **{res['dep']:,.0f}원**의 감가상각비 발생 (최대 {dep_period}년)
            3. **현금흐름**: 초기(감가상각 기간)에는 **{res['first_ocf']:,.0f}원**의 세후 현금흐름 발생
            4. **미래 가치 누적**: 총 **{active_period}년** 간의 현금흐름이 할인율 **{rate_pct}%**로 할인되어 반영됨
            """)

            st.divider()
            
            st.subheader("📉 좀비 배관 민감도 분석 (유지/관리비 인상 리스크)")
            if res['is_zombie']:
                st.error("🚨 이미 감가상각 종료 후 운영 적자가 발생하는 **좀비 배관** 상태입니다.")
            elif res['margin'] <= 0:
                st.error("🚨 매출 마진 자체가 0 이하인 구조적 적자 상태입니다.")
            elif res['zombie_threshold_pct'] == float('inf'):
                st.success("✅ 유지관리비가 0원으로 설정되어 있어 좀비 배관 전락 위험이 없습니다.")
            else:
                st.warning(f"⚠️ 현재 설정된 판관비(유지비+관리비)가 향후 **약 {res['zombie_threshold_pct']:,.1f}% 이상 상승**하면, 감가상각 종료 후 적자로 전환되는 **'좀비 배관'**이 됩니다.")
                st.info(f"👉 **마진 방어선:** 총 마진({res['margin']:,.0f}원) = 판관비 합계({res['sga']:,.0f}원) + 잉여 마진({res['margin'] - res['sga']:,.0f}원)")
                
            st.divider()
            
            # [추가된 부분] 30년 / 50년 달성 목표 판매량 비교
            st.subheader("💡 경제성 확보를 위한 제언")
            
            req_vol_m3_30 = res['required_vol_30'] / 42.563
            req_vol_m3_50 = res['required_vol_50'] / 42.563
            sim_vol_m3 = sim_vol / 42.563
            
            if res['npv'] < 0:
                st.error(f"⚠️ 현재 분석 조건으로는 경제성이 부족합니다. (목표 IRR {rate_pct}%)")
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    st.markdown("👉 **[현재 기준] 30년 경제성 만족을 위한 최소 판매량**")
                    st.info(f"### **{res['required_vol_30']:,.0f} MJ**\n\n≙ **{req_vol_m3_30:,.0f} ㎥**")
                with col_m2:
                    st.markdown("👉 **[장기 기준] 50년 경제성 만족을 위한 안정 판매량**")
                    st.success(f"### **{res['required_vol_50']:,.0f} MJ**\n\n≙ **{req_vol_m3_50:,.0f} ㎥**")
            else:
                st.success(f"✅ 현재 판매량은 경제성 확보 기준을 충족합니다.")
                col_m1, col_m2, col_m3 = st.columns(3)
                with col_m1:
                    st.markdown("👉 **현재 입력 판매량**")
                    st.success(f"**{sim_vol:,.0f} MJ**\n\n(≙ {sim_vol_m3:,.0f} ㎥)")
                with col_m2:
                    st.markdown("👉 **30년 기준 (최소)**")
                    st.info(f"**{res['required_vol_30']:,.0f} MJ**\n\n(≙ {req_vol_m3_30:,.0f} ㎥)")
                with col_m3:
                    st.markdown("👉 **50년 기준 (안정)**")
                    st.info(f"**{res['required_vol_50']:,.0f} MJ**\n\n(≙ {req_vol_m3_50:,.0f} ㎥)")
        
        chart_data = pd.DataFrame({
            "Year": range(0, int(active_period) + 1),
            "Cumulative Cash Flow": np.cumsum(res['flows'])
        })
        st.line_chart(chart_data, x="Year", y="Cumulative Cash Flow")

        with st.expander("📊 [세부 분석] 연도별 손익 계산 및 NPV/IRR 상세 내역 보기"):
            
            years = [str(i) for i in range(1, int(active_period) + 1)]
            
            val_sales = sim_rev
            val_cogs = sim_cost
            val_margin = sim_rev - sim_cost
            val_basic = sim_basic_rev
            val_maint = sim_len * c_maint
            val_adm = (sim_len * c_adm_m) + (sim_jeon * c_adm_jeon)
            val_sga = val_maint + val_adm
            
            pnl_dict = {
                "구분": [
                    "가스 판매액", "가스 판매 원가", "수익 (가스판매수익)", "수익 (기본요금수익)", 
                    "판매관리비 (배관 유지비)", "판매관리비 (일반 관리비)", "판매관리비 (소계)", 
                    "감가상각비", "세전 수요개발 기대이익", "세후 당기 손익", "세후 수요개발 기대이익"
                ]
            }
            
            npv_dict = {
                "구분": [
                    "세후 수요개발 기대이익", "배관공사 투자금액", "시설 분담금", "기타 이익", 
                    "Free Cash Flow", "순현재가치(NPV) 환산", "미회수 투자액"
                ]
            }
            
            net_inv = sim_inv - sim_contrib - sim_other
            npv_dict["초기투자"] = [0, -sim_inv, sim_contrib, sim_other, -net_inv, -net_inv, -net_inv]
            
            cum_pv = -net_inv
            
            for i, y in enumerate(years):
                period = i + 1
                current_dep = sim_inv / dep_period if (dep_period > 0 and period <= dep_period) else 0
                current_ebit = (val_margin + val_basic) - val_sga - current_dep
                current_ni = current_ebit * (1 - TAX)
                current_ocf = current_ni + current_dep
                
                pnl_dict[y] = [val_sales, val_cogs, val_margin, val_basic, val_maint, val_adm, val_sga, current_dep, current_ebit, current_ni, current_ocf]
                
                discounted_fcf = current_ocf / ((1 + RATE) ** period)
                cum_pv += discounted_fcf
                npv_dict[y] = [current_ocf, 0, 0, 0, current_ocf, discounted_fcf, cum_pv]
                
            pnl_df = pd.DataFrame(pnl_dict)
            npv_df = pd.DataFrame(npv_dict)
            
            st.markdown("#### 📝 연도별 손익 계산")
            st.dataframe(pnl_df.style.format({y: "{:,.0f}" for y in years}), use_container_width=True, hide_index=True)

            st.markdown("<br>", unsafe_allow_html=True)
            
            st.markdown("#### 💰 NPV 및 IRR 평가")
            format_dict = {"초기투자": "{:,.0f}"}
            format_dict.update({y: "{:,.0f}" for y in years})
            st.dataframe(npv_df.style.format(format_dict), use_container_width=True, hide_index=True)

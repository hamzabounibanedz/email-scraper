# Email Response Classification Types

This document lists all automatic classification types used in the Gmail response classification workflow.

## Classification Types (14 Total)

### 1. **Potential Buyers** 🎯
**Keywords**: buy, purchase, order, price, cost, pricing, quote, interested in buying, ready to buy, want to buy  
**Description**: Expressing strong purchase intent or asking about pricing  
**Action**: High priority follow-up, send pricing/quotes

### 2. **Demo Scheduled** 📅
**Keywords**: demo, schedule, meeting, call, zoom, teams, calendar, appointment, available, time slot  
**Description**: Agreed to schedule a demo or meeting  
**Action**: Confirm demo details, send calendar invite

### 3. **Leads** 💡
**Keywords**: interested, tell me more, more information, info, details, how does, what is, questions, curious, learn more  
**Description**: Interested and asking general questions  
**Action**: Send detailed information, answer questions

### 4. **More Information** 📋
**Keywords**: more info, more details, specifications, specs, features, benefits, how it works  
**Description**: Requesting specific details or documentation  
**Action**: Send product sheets, case studies, detailed info

### 5. **Price Objection** 💰
**Keywords**: expensive, too much, cost, budget, afford, cheaper, discount, deal  
**Description**: Interested but concerned about price  
**Action**: Address pricing concerns, offer alternatives, payment plans

### 6. **Not Right Time** ⏰
**Keywords**: not now, later, next month, next year, busy, timing, not the right time, future  
**Description**: Interested but timing is not right  
**Action**: Schedule follow-up for later date, add to nurture sequence

### 7. **Follow-up Needed** 🔄
**Keywords**: think about, consider, discuss, team, manager, decision, review, evaluate  
**Description**: Needs time to consider or discuss with team  
**Action**: Schedule follow-up, send decision-making resources

### 8. **Not Interested** ❌
**Keywords**: not interested, no thanks, decline, pass, not for us, don't need  
**Description**: Politely declining the offer  
**Action**: Respect decision, optionally ask for feedback

### 9. **Wrong Person** 👤
**Keywords**: wrong person, not me, not the right, different department, forwarded  
**Description**: Email reached wrong contact  
**Action**: Ask for correct contact, update database

### 10. **Out of Office** 🏖️
**Keywords**: out of office, ooo, away, vacation, unavailable, auto-reply, automatic reply  
**Description**: Auto-reply messages  
**Action**: Wait for return, schedule follow-up after return date

### 11. **Unsubscribe** 🚫
**Keywords**: unsubscribe, remove, stop, opt out, don't email, no more emails  
**Description**: Requesting to be removed from list  
**Action**: Remove from list immediately, update master tracking

### 12. **Customer** ✅
**Keywords**: purchased, bought, customer, already have, using, implemented  
**Description**: Already converted to customer  
**Action**: Move to customer database, focus on retention

### 13. **Bounce** 📧
**Description**: Email delivery failure (handled by email provider)  
**Action**: Remove from list, mark as invalid email

### 14. **Unknown** ❓
**Description**: Could not be automatically classified  
**Action**: Manual review required, may need keyword adjustment

## Classification Priority

Classifications are checked in this order (first match wins):
1. Potential Buyers
2. Demo Scheduled
3. Leads
4. More Information
5. Price Objection
6. Not Right Time
7. Follow-up Needed
8. Not Interested
9. Wrong Person
10. Out of Office
11. Unsubscribe
12. Customer
13. Unknown (default if no match)

## Customization

You can adjust keywords in the n8n Code Node to match your specific use case and language patterns. Test with sample email responses to refine the classification logic.

## CSV Files Generated

Each classification type creates/updates its own CSV file in `csv/` folder:
- `csv/potential_buyers.csv`
- `csv/demo_scheduled.csv`
- `csv/leads.csv`
- `csv/more_information.csv`
- `csv/price_objection.csv`
- `csv/not_right_time.csv`
- `csv/follow_up_needed.csv`
- `csv/not_interested.csv`
- `csv/wrong_person.csv`
- `csv/out_of_office.csv`
- `csv/unsubscribes.csv`
- `csv/customers.csv`
- `csv/bounces.csv`
- `csv/unknown.csv`

All classifications also update `csv/master_tracking.csv` with the classification and reply status.

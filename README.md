Coding Project:
Swiss Style Tournament System.

*Workflow*
1. **Create Tournament**  
   - **Enter Tournament Name**  
   - **Add/Remove Players**  
     - Checklist of current entries  
     - **Add Entry** button at bottom  
       - Name  
       - Elo  
   - **Set Games per Match**  
     - Best of 1, 3, 5, etc
     - - +/- menu  
   - **Display First Set**  
     - High/Low seeding by default  
     - Edit player positions 
     - Edit default Elo gain/loss  
2. **Start Tournament**  
   - **Select Match**  
     - Adjust Elo gain/loss for that match  
     - Select Winner  
     - Submit result  
   - Once all matches in Set 1 conclude, repeat **Start Tournament** for Set 2  
3. **Display Results**
   - **Display final bracket**
    - Show +/- ELO after each match

Requirements:
Basic ELO system that has the ability to modify how much elo is gained/lost
Save names and elo of players
Ability to adjust how many rounds are played per match. (3 rounds = 1 match, a tournament is multiple matches)
Players do not need to access this system, only the match admin.

TODO: 
Sanitize player names
Add check so ELO cannot drop below 0